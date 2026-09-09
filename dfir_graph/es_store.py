"""Elasticsearch backend for Evidence Atlas. Same read interface as store.Store.

Primary workflow: ingest to SQLite first (existing pipeline), then sync to ES
with ``sync_from_sqlite``. The ES backend provides full-text search, Kibana
integration, and the scale needed for Sigma rule matching.
"""

import json
import os

from .es_mappings import (
    ALL_PREFIXES, index_name, legacy_index_name, create_indices, delete_indices, record_to_ecs,
)
from .model import dumps


def _connect(hosts=None, api_key=None):
    from elasticsearch import Elasticsearch

    hosts = hosts or os.environ.get("EA_ES_HOSTS", "http://localhost:9200")
    if isinstance(hosts, str):
        hosts = [h.strip() for h in hosts.split(",") if h.strip()]
    kwargs = {"hosts": hosts, "request_timeout": 30}
    api_key = api_key or os.environ.get("EA_ES_API_KEY")
    if api_key:
        kwargs["api_key"] = api_key
    return Elasticsearch(**kwargs)


class ESStore:
    """Elasticsearch-backed store with the same read API as sqlite Store."""

    def __init__(self, hosts=None, api_key=None, es=None):
        self.es = es or _connect(hosts, api_key)

    def close(self):
        self.es.close()

    def ping(self):
        return self.es.ping()

    def info(self):
        return self.es.info()

    # ── index lifecycle ──────────────────────────────────────────────

    def ensure_indices(self, case_id):
        return create_indices(self.es, case_id)

    def drop_indices(self, case_id):
        return delete_indices(self.es, case_id)

    def list_cases(self):
        indices = self.es.indices.get(index="ea-records-*", ignore_unavailable=True)
        cases = set()
        for name, info in indices.items():
            case_id = info.get("mappings", {}).get("_meta", {}).get("ea_case_id")
            if case_id is not None:
                cases.add(case_id)
                continue
            # Legacy indices did not retain the exact ID in their names.
            response = self.es.search(index=name, size=0, body={
                "aggs": {"cases": {"terms": {"field": "ea.case_id", "size": 2}}}})
            buckets = response["aggregations"]["cases"]["buckets"]
            if len(buckets) > 1:
                raise ValueError("Legacy ES index contains multiple cases; re-sync each SQLite case: " + name)
            cases.update(b["key"] for b in buckets)
        return sorted(cases)

    def _read_index(self, prefix, case_id):
        name = index_name(prefix, case_id)
        if self.es.indices.exists(index=name):
            return name
        legacy = legacy_index_name(prefix, case_id)
        if self.es.indices.exists(index=legacy):
            field = "ea.case_id" if prefix == "records" else "case_id"
            foreign = self.es.count(index=legacy, body={"query": {"bool": {
                "must_not": [{"term": {field: case_id}}]}}})["count"]
            if foreign:
                raise ValueError("Legacy ES case collision; re-sync from SQLite before reading: " + legacy)
            return legacy
        return name

    # ── write (node / edge / issue) ──────────────────────────────────

    def node(self, case_id, label, identity, display, props=None):
        from .model import uid
        node_id = uid(label, case_id, identity)
        idx = index_name("nodes", case_id)
        self.es.options(ignore_status=409).index(index=idx, id=node_id, document={
            "case_id": case_id, "label": label, "display": str(display),
            "props": props or {},
        }, op_type="create")
        return node_id

    def edge(self, case_id, source, target, kind, evidence=None, basis="observed", props=None):
        from .model import uid
        props = props or {}
        edge_id = uid("edge", case_id, source, target, kind, evidence, basis, props)
        idx = index_name("edges", case_id)
        self.es.options(ignore_status=409).index(index=idx, id=edge_id, document={
            "case_id": case_id, "source": source, "target": target,
            "type": kind, "evidence_id": evidence, "basis": basis,
            "props": props,
        }, op_type="create")
        return edge_id

    def issue(self, case_id, source_id, record_id, code, message):
        from .model import uid
        issue_id = uid("issue", case_id, source_id, record_id, code, message)
        idx = index_name("issues", case_id)
        self.es.options(ignore_status=409).index(index=idx, id=issue_id, document={
            "case_id": case_id, "source_id": source_id,
            "record_id": record_id, "code": code, "message": message,
        }, op_type="create")

    # ── bulk sync from SQLite ────────────────────────────────────────

    def sync_from_sqlite(self, sqlite_path, case_id=None, progress=None):
        """Push all data from a SQLite database into Elasticsearch.

        If case_id is given, only that case is synced. Otherwise all cases.
        Returns counts of documents indexed per index type.
        """
        from .store import Store

        progress = progress or (lambda msg: None)
        store = Store(sqlite_path, readonly=True)
        try:
            store.db.execute("BEGIN")  # One consistent SQLite read snapshot.
            if case_id and not store.db.execute("SELECT 1 FROM cases WHERE id=?", (case_id,)).fetchone():
                raise ValueError("Unknown SQLite case: " + case_id)
            cases = ([case_id] if case_id
                     else [r[0] for r in store.db.execute("SELECT id FROM cases")])
            totals = {}
            for cid in cases:
                progress(f"Syncing case: {cid}")
                self.ensure_indices(cid)
                totals[cid] = self._sync_case(store, cid, progress)
            return totals
        finally:
            store.close()

    def _sync_case(self, store, case_id, progress):
        counts = {}

        counts["sources"] = self._bulk_sources(store, case_id, progress)
        counts["records"] = self._bulk_records(store, case_id, progress)
        counts["nodes"] = self._bulk_nodes(store, case_id, progress)
        counts["edges"] = self._bulk_edges(store, case_id, progress)
        counts["issues"] = self._bulk_issues(store, case_id, progress)

        for prefix in ALL_PREFIXES:
            idx = index_name(prefix, case_id)
            self.es.indices.refresh(index=idx)

        self.activate_case(case_id)
        return counts

    def activate_case(self, case_id):
        """Expose only the completed current projection to Kibana/search views."""
        response = self.es.indices.update_aliases(actions=[{"add": {
            "index": index_name(prefix, case_id), "alias": "ea-current-" + prefix}}
            for prefix in ALL_PREFIXES])
        if not response.get("acknowledged"):
            raise ValueError("ES alias update was not acknowledged; re-run es-sync")

    def _bulk_sources(self, store, case_id, progress):
        idx = index_name("sources", case_id)
        rows = store.db.execute(
            "SELECT * FROM sources WHERE case_id=?", (case_id,))
        actions = []
        total = 0
        for row in rows:
            doc = {
                "case_id": row["case_id"],
                "relative_path": row["relative_path"],
                "absolute_path": row["absolute_path"],
                "sha256": row["sha256"],
                "bytes": row["bytes"],
                "adapter": row["adapter"],
                "adapter_version": row["adapter_version"],
                "status": row["status"],
                "rows_count": row["rows_count"],
                "error": row["error"],
                "context": json.loads(row["context_json"]),
            }
            actions.append({"index": {"_index": idx, "_id": row["id"]}})
            actions.append(doc)
            if len(actions) >= 2000:
                total += self._send_bulk(actions, progress, "sources")
                actions = []
        count = self._send_bulk(actions, progress, "sources")
        return total + count

    def _bulk_records(self, store, case_id, progress):
        idx = index_name("records", case_id)
        source_cache = {}
        for s in store.db.execute("SELECT * FROM sources WHERE case_id=?", (case_id,)):
            source_cache[s["id"]] = dict(s)

        actions = []
        total = 0
        cursor = store.db.execute(
            """SELECT r.* FROM records r
               JOIN sources s ON s.id = r.source_id
               WHERE s.case_id = ?""", (case_id,))
        for row in cursor:
            row_dict = dict(row)
            source_row = source_cache.get(row["source_id"])
            doc = record_to_ecs(row_dict, source_row)
            actions.append({"index": {"_index": idx, "_id": row["id"]}})
            actions.append(doc)
            total += 1
            if len(actions) >= 2000:
                self._send_bulk(actions, progress, f"records ({total:,})")
                actions = []
        if actions:
            self._send_bulk(actions, progress, f"records ({total:,})")
        progress(f"  records: {total:,} indexed")
        return total

    def _bulk_nodes(self, store, case_id, progress):
        idx = index_name("nodes", case_id)
        actions = []
        total = 0
        for row in store.db.execute("SELECT * FROM nodes WHERE case_id=?", (case_id,)):
            doc = {
                "case_id": row["case_id"],
                "label": row["label"],
                "display": row["display"],
                "props": json.loads(row["props_json"]),
            }
            actions.append({"index": {"_index": idx, "_id": row["id"]}})
            actions.append(doc)
            if len(actions) >= 2000:
                total += self._send_bulk(actions, progress, "nodes")
                actions = []
        count = self._send_bulk(actions, progress, "nodes")
        return total + count

    def _bulk_edges(self, store, case_id, progress):
        idx = index_name("edges", case_id)
        actions = []
        total = 0
        for row in store.db.execute("SELECT * FROM edges WHERE case_id=?", (case_id,)):
            doc = {
                "case_id": row["case_id"],
                "source": row["source"],
                "target": row["target"],
                "type": row["type"],
                "evidence_id": row["evidence_id"],
                "basis": row["basis"],
                "props": json.loads(row["props_json"]),
            }
            actions.append({"index": {"_index": idx, "_id": row["id"]}})
            actions.append(doc)
            if len(actions) >= 2000:
                total += self._send_bulk(actions, progress, "edges")
                actions = []
        count = self._send_bulk(actions, progress, "edges")
        return total + count

    def _bulk_issues(self, store, case_id, progress):
        idx = index_name("issues", case_id)
        actions = []
        total = 0
        for row in store.db.execute("SELECT * FROM issues WHERE case_id=?", (case_id,)):
            doc = {
                "case_id": row["case_id"],
                "source_id": row["source_id"],
                "record_id": row["record_id"],
                "code": row["code"],
                "message": row["message"],
            }
            actions.append({"index": {"_index": idx, "_id": row["id"]}})
            actions.append(doc)
            if len(actions) >= 2000:
                total += self._send_bulk(actions, progress, "issues")
                actions = []
        count = self._send_bulk(actions, progress, "issues")
        return total + count

    def _send_bulk(self, actions, progress, label=""):
        if not actions:
            return 0
        response = self.es.bulk(body=actions, refresh=False)
        count = len(actions) // 2
        items = response.get("items", [])
        failures = [next(iter(item.values())) for item in items
                    if any(value.get("error") or not 200 <= value.get("status", 0) < 300
                           for value in item.values())]
        if response.get("errors") or failures or len(items) != count:
            # Do not leak raw evidence in error output or claim partial writes succeeded.
            examples = ", ".join(str(item.get("_id", "?")) + ":" +
                str(item.get("status", "?")) for item in failures[:3])
            raise ValueError(f"ES bulk {label}: incomplete ({len(failures)} failed, "
                             f"{len(items)}/{count} receipts). Re-run es-sync. {examples}")
        progress(f"  {label}: {count} indexed")
        return count

    # ── read API (same interface as store.Store) ─────────────────────

    def stats(self, case_id=None):
        cases = [case_id] if case_id else self.list_cases()
        if not cases:
            return {"cases": 0, "sources": {}, "records": {},
                    "nodes": {}, "edges": {}, "issues": {}, "imports": []}

        result = {"cases": len(cases), "sources": {}, "records": {},
                  "nodes": {}, "edges": {}, "issues": {}, "imports": []}

        for cid in cases:
            rec_idx = self._read_index("records", cid)
            if self.es.indices.exists(index=rec_idx):
                agg = self.es.search(index=rec_idx, size=0, body={
                    "aggs": {"kinds": {"terms": {"field": "ea.kind", "size": 50}}}
                })
                for bucket in agg["aggregations"]["kinds"]["buckets"]:
                    result["records"][bucket["key"]] = (
                        result["records"].get(bucket["key"], 0) + bucket["doc_count"])

            src_idx = self._read_index("sources", cid)
            if self.es.indices.exists(index=src_idx):
                agg = self.es.search(index=src_idx, size=0, body={
                    "aggs": {"statuses": {"terms": {"field": "status", "size": 20}}}
                })
                for bucket in agg["aggregations"]["statuses"]["buckets"]:
                    result["sources"][bucket["key"]] = (
                        result["sources"].get(bucket["key"], 0) + bucket["doc_count"])

            node_idx = self._read_index("nodes", cid)
            if self.es.indices.exists(index=node_idx):
                agg = self.es.search(index=node_idx, size=0, body={
                    "aggs": {"labels": {"terms": {"field": "label", "size": 50}}}
                })
                for bucket in agg["aggregations"]["labels"]["buckets"]:
                    result["nodes"][bucket["key"]] = (
                        result["nodes"].get(bucket["key"], 0) + bucket["doc_count"])

            edge_idx = self._read_index("edges", cid)
            if self.es.indices.exists(index=edge_idx):
                agg = self.es.search(index=edge_idx, size=0, body={
                    "aggs": {"types": {"terms": {"field": "type", "size": 50}}}
                })
                for bucket in agg["aggregations"]["types"]["buckets"]:
                    result["edges"][bucket["key"]] = (
                        result["edges"].get(bucket["key"], 0) + bucket["doc_count"])

            iss_idx = self._read_index("issues", cid)
            if self.es.indices.exists(index=iss_idx):
                agg = self.es.search(index=iss_idx, size=0, body={
                    "aggs": {"codes": {"terms": {"field": "code", "size": 50}}}
                })
                for bucket in agg["aggregations"]["codes"]["buckets"]:
                    result["issues"][bucket["key"]] = (
                        result["issues"].get(bucket["key"], 0) + bucket["doc_count"])

        return result

    def evidence(self, record_id, case_id=None):
        cases = [case_id] if case_id else self.list_cases()
        for cid in cases:
            idx = self._read_index("records", cid)
            if not self.es.indices.exists(index=idx):
                continue
            try:
                doc = self.es.get(index=idx, id=record_id)
                src = doc["_source"]
                source_id = src.get("ea.source_id")
                source_info = {}
                if source_id:
                    src_idx = self._read_index("sources", cid)
                    try:
                        sdoc = self.es.get(index=src_idx, id=source_id)
                        source_info = sdoc["_source"]
                    except Exception as exc:
                        if getattr(exc, "status_code", None) != 404:
                            raise
                return {
                    "id": record_id,
                    "source_id": source_id,
                    "ordinal": src.get("ea.ordinal", 0),
                    "kind": src.get("ea.kind", ""),
                    "host": src.get("host.name", ""),
                    "scope": src.get("ea.scope", ""),
                    "time_raw": src.get("ea.time_raw", ""),
                    "time_utc": src.get("@timestamp"),
                    "raw": src.get("ea.raw", {}),
                    "relative_path": source_info.get("relative_path", ""),
                    "absolute_path": source_info.get("absolute_path", ""),
                    "sha256": source_info.get("sha256", ""),
                    "adapter": source_info.get("adapter", ""),
                    "adapter_version": source_info.get("adapter_version", ""),
                    "context": source_info.get("context", {}),
                }
            except Exception as exc:
                if getattr(exc, "status_code", None) != 404:
                    raise
                continue
        return None

    def search(self, query="", label=None, limit=30, case_id=None):
        cases = [case_id] if case_id else self.list_cases()
        indices = [self._read_index("nodes", c) for c in cases
                   if self.es.indices.exists(index=self._read_index("nodes", c))]
        if not indices:
            return []

        must = []
        if query:
            must.append({"bool": {"should": [
                {"match": {"display": {"query": query, "fuzziness": "AUTO"}}},
                {"term": {"_id": query}},
            ]}})
        if label:
            must.append({"term": {"label": label}})

        body = {
            "query": {"bool": {"must": must}} if must else {"match_all": {}},
            "size": min(max(limit, 1), 200),
            "sort": [{"label": "asc"}, {"display.keyword": "asc"}],
        }
        resp = self.es.search(index=",".join(indices), body=body)
        results = []
        for hit in resp["hits"]["hits"]:
            src = hit["_source"]
            results.append({
                "id": hit["_id"],
                "case_id": src.get("case_id", ""),
                "label": src.get("label", ""),
                "display": src.get("display", ""),
                "properties": src.get("props", {}),
            })
        return results

    def neighborhood(self, node_id, limit=40, case_id=None):
        cases = [case_id] if case_id else self.list_cases()
        limit = min(max(limit, 1), 150)

        center = None
        center_case = None
        for cid in cases:
            idx = self._read_index("nodes", cid)
            if not self.es.indices.exists(index=idx):
                continue
            try:
                doc = self.es.get(index=idx, id=node_id)
                center = doc["_source"]
                center_case = cid
                break
            except Exception as exc:
                if getattr(exc, "status_code", None) != 404:
                    raise
                continue
        if not center:
            return None

        edge_idx = self._read_index("edges", center_case)
        if not self.es.indices.exists(index=edge_idx):
            return {"center": node_id, "nodes": [self._node_dict(node_id, center)],
                    "edges": [], "truncated": False}

        resp = self.es.search(index=edge_idx, body={
            "query": {"bool": {"should": [
                {"term": {"source": node_id}},
                {"term": {"target": node_id}},
            ]}},
            "size": limit + 1,
            "sort": [{"type": "asc"}],
        })

        edges = []
        node_ids = {node_id}
        truncated = len(resp["hits"]["hits"]) > limit
        for hit in resp["hits"]["hits"][:limit]:
            src = hit["_source"]
            edge = {
                "id": hit["_id"],
                "case_id": src.get("case_id", ""),
                "source": src["source"],
                "target": src["target"],
                "type": src["type"],
                "evidence_id": src.get("evidence_id"),
                "basis": src.get("basis", "observed"),
                "properties": src.get("props", {}),
            }
            edges.append(edge)
            node_ids.update([src["source"], src["target"]])

        node_idx = self._read_index("nodes", center_case)
        nodes = []
        for nid in sorted(node_ids):
            try:
                doc = self.es.get(index=node_idx, id=nid)
                nodes.append(self._node_dict(nid, doc["_source"]))
            except Exception as exc:
                if getattr(exc, "status_code", None) != 404:
                    raise
                nodes.append({"id": nid, "case_id": center_case,
                              "label": "?", "display": nid, "properties": {}})

        return {"center": node_id, "nodes": nodes, "edges": edges,
                "truncated": truncated}

    @staticmethod
    def _node_dict(node_id, src):
        return {
            "id": node_id,
            "case_id": src.get("case_id", ""),
            "label": src.get("label", ""),
            "display": src.get("display", ""),
            "properties": src.get("props", {}),
        }

    # ── ES-specific queries ──────────────────────────────────────────

    def search_records(self, query, case_id, size=50):
        idx = self._read_index("records", case_id)
        if not self.es.indices.exists(index=idx):
            return []
        escaped = query.replace("\\", "\\\\").replace('"', '\\"')
        body = {
            "query": {"query_string": {
                "query": f"*{escaped}*",
                "fields": [
                    "process.name", "process.command_line",
                    "process.parent.name", "user.name", "user.id",
                    "event.provider", "event.code", "host.name",
                    "ea.kind",
                ],
                "default_operator": "AND",
            }},
            "size": size,
            "sort": [{"@timestamp": {"order": "desc", "unmapped_type": "date"}}],
        }
        resp = self.es.search(index=idx, body=body)
        return [{"id": h["_id"], **h["_source"]} for h in resp["hits"]["hits"]]

    def count_by_field(self, field, case_id, size=30):
        idx = self._read_index("records", case_id)
        if not self.es.indices.exists(index=idx):
            return {}
        resp = self.es.search(index=idx, size=0, body={
            "aggs": {"group": {"terms": {"field": field, "size": size}}}
        })
        return {b["key"]: b["doc_count"]
                for b in resp["aggregations"]["group"]["buckets"]}

    def date_histogram(self, case_id, interval="1h"):
        idx = self._read_index("records", case_id)
        if not self.es.indices.exists(index=idx):
            return []
        resp = self.es.search(index=idx, size=0, body={
            "aggs": {"timeline": {"date_histogram": {
                "field": "@timestamp",
                "fixed_interval": interval,
            }}}
        })
        return [{"time": b["key_as_string"], "count": b["doc_count"]}
                for b in resp["aggregations"]["timeline"]["buckets"]
                if b["doc_count"] > 0]
