"""SQLite staging and graph projection. Raw rows and graph claims are separate."""

import json
import sqlite3
from pathlib import Path

from .model import dumps, uid

SCHEMA_VERSION = "1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS imports (
 id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id), root TEXT NOT NULL,
 started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, options_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sources (
 id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id), relative_path TEXT NOT NULL,
 absolute_path TEXT NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL,
 adapter TEXT NOT NULL, status TEXT NOT NULL, rows_count INTEGER NOT NULL DEFAULT 0,
 error TEXT, context_json TEXT NOT NULL, adapter_version TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS import_sources (
 import_id TEXT NOT NULL REFERENCES imports(id), source_id TEXT NOT NULL REFERENCES sources(id),
 PRIMARY KEY(import_id,source_id));
CREATE TABLE IF NOT EXISTS records (
 id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id), ordinal INTEGER NOT NULL,
 raw_json TEXT NOT NULL, kind TEXT NOT NULL, host TEXT, scope TEXT, time_raw TEXT, time_utc TEXT,
 UNIQUE(source_id,ordinal));
CREATE INDEX IF NOT EXISTS records_kind_time ON records(kind,time_utc);
CREATE TABLE IF NOT EXISTS nodes (
 id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id), label TEXT NOT NULL,
 display TEXT NOT NULL, props_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS nodes_label ON nodes(label);
CREATE INDEX IF NOT EXISTS nodes_case ON nodes(case_id);
CREATE TABLE IF NOT EXISTS edges (
 id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id),
 source TEXT NOT NULL REFERENCES nodes(id), target TEXT NOT NULL REFERENCES nodes(id),
 type TEXT NOT NULL, evidence_id TEXT REFERENCES records(id),
 basis TEXT NOT NULL, props_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS edges_source ON edges(source);
CREATE INDEX IF NOT EXISTS edges_target ON edges(target);
CREATE INDEX IF NOT EXISTS edges_evidence ON edges(evidence_id);
CREATE TABLE IF NOT EXISTS issues (
 id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id), source_id TEXT REFERENCES sources(id),
 record_id TEXT REFERENCES records(id), code TEXT NOT NULL, message TEXT NOT NULL);
"""


class Store:
    def __init__(self, path, readonly=False):
        path = Path(path).resolve()
        self.path = path
        if readonly:
            self.db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=5000")
        if not readonly:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript(SCHEMA)
            previous = self.db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if previous and previous[0] != SCHEMA_VERSION:
                raise ValueError("Unsupported staging schema; use a new database")
            self.db.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version',?)", (SCHEMA_VERSION,))
            self.db.commit()

    def close(self):
        self.db.close()

    def node(self, case_id, label, identity, display, props=None):
        node_id = uid(label, case_id, identity)
        # Entity properties are immutable identity descriptions. Event-specific
        # facts always live on observations, never last-writer-wins entity fields.
        self.db.execute("INSERT OR IGNORE INTO nodes VALUES (?,?,?,?,?)",
                        (node_id, case_id, label, str(display), dumps(props or {})))
        return node_id

    def edge(self, case_id, source, target, kind, evidence=None, basis="observed", props=None):
        props = props or {}
        edge_id = uid("edge", case_id, source, target, kind, evidence, basis, props)
        self.db.execute("INSERT OR IGNORE INTO edges VALUES (?,?,?,?,?,?,?,?)",
                        (edge_id, case_id, source, target, kind, evidence, basis, dumps(props)))
        return edge_id

    def issue(self, case_id, source_id, record_id, code, message):
        issue_id = uid("issue", case_id, source_id, record_id, code, message)
        self.db.execute("INSERT OR IGNORE INTO issues VALUES (?,?,?,?,?,?)",
                        (issue_id, case_id, source_id, record_id, code, message))

    def stats(self):
        grouped = lambda table, field: {r[0]: r[1] for r in self.db.execute(
            f"SELECT {field},count(*) FROM {table} GROUP BY {field}")}
        return {"cases": self.db.execute("SELECT count(*) FROM cases").fetchone()[0],
                "sources": grouped("sources", "status"), "records": grouped("records", "kind"),
                "nodes": grouped("nodes", "label"), "edges": grouped("edges", "type"),
                "issues": grouped("issues", "code"),
                "imports": [dict(r) for r in self.db.execute("SELECT id,status,started_at,finished_at FROM imports ORDER BY started_at DESC LIMIT 5")]}

    def evidence(self, record_id):
        row = self.db.execute("""SELECT r.*,s.relative_path,s.absolute_path,s.sha256,
            s.adapter,s.adapter_version,s.context_json FROM records r JOIN sources s ON s.id=r.source_id
            WHERE r.id=?""", (record_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["raw"] = json.loads(result.pop("raw_json"))
        result["context"] = json.loads(result.pop("context_json"))
        return result

    def search(self, query="", label=None, limit=30):
        pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        sql = "SELECT * FROM nodes WHERE (display LIKE ? ESCAPE '\\' OR id=?)"
        args = [pattern, query]
        if label:
            sql += " AND label=?"
            args.append(label)
        sql += " ORDER BY label,display,id LIMIT ?"
        args.append(min(max(limit, 1), 200))
        return [self.node_dict(r) for r in self.db.execute(sql, args)]

    @staticmethod
    def node_dict(row):
        data = dict(row)
        data["properties"] = json.loads(data.pop("props_json"))
        return data

    def neighborhood(self, node_id, limit=40):
        limit = min(max(limit, 1), 150)
        center = self.db.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        if not center:
            return None
        edges = [dict(r) for r in self.db.execute("""SELECT * FROM edges
                    WHERE source=? OR target=? ORDER BY type,id LIMIT ?""", (node_id, node_id, limit + 1))]
        truncated = len(edges) > limit
        edges = edges[:limit]
        ids = {node_id}
        for edge in edges:
            edge["properties"] = json.loads(edge.pop("props_json"))
            ids.update([edge["source"], edge["target"]])
        nodes = [self.node_dict(self.db.execute("SELECT * FROM nodes WHERE id=?", (key,)).fetchone()) for key in sorted(ids)]
        return {"center": node_id, "nodes": nodes, "edges": edges, "truncated": truncated}


    def graph_neighbors(self, node_id, depth=1, node_limit=100, edge_limit=180,
                        include_structure=False, scope="", case_id=None):
        """Bounded, deterministic, read-only BFS; links remain evidence claims.

        Shared FilePath/Account nodes may span snapshots. Edges retain each
        source record's scope; an optional scope restricts claims before BFS.
        Structural hubs are excluded by default to avoid expanding a whole case.
        """
        depth = int(depth)
        if depth not in (1, 2):
            raise ValueError("Graph depth must be 1 or 2")
        node_limit = min(max(int(node_limit), 2), 200)
        edge_limit = min(max(int(edge_limit), 1), 400)
        center = self.db.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        if not center or (case_id and center["case_id"] != case_id):
            return None
        case_id = center["case_id"]
        nodes = {node_id: self.node_dict(center)}
        hops = {node_id: 0}
        edges, frontier, truncated = {}, [node_id], False
        structural = ("Case", "Host", "Snapshot", "EvidenceSource")
        for hop in range(1, depth + 1):
            following = []
            for current in frontier:
                sql = """SELECT e.*,r.scope AS evidence_scope,r.host AS evidence_host
                    FROM edges e JOIN nodes s ON s.id=e.source JOIN nodes t ON t.id=e.target
                    LEFT JOIN records r ON r.id=e.evidence_id
                    LEFT JOIN sources rs ON rs.id=r.source_id
                    WHERE e.case_id=? AND s.case_id=? AND t.case_id=?
                    AND (e.evidence_id IS NULL OR rs.case_id=?)
                    AND (e.source=? OR e.target=?)"""
                args = [case_id, case_id, case_id, case_id, current, current]
                if not include_structure:
                    sql += " AND s.label NOT IN (?,?,?,?) AND t.label NOT IN (?,?,?,?)"
                    args.extend(structural * 2)
                if scope:
                    sql += " AND (e.evidence_id IS NULL OR r.scope=?)"
                    args.append(scope)
                sql += " ORDER BY e.type,e.id LIMIT ?"
                args.append(edge_limit + 1)
                rows = self.db.execute(sql, args).fetchall()
                if len(rows) > edge_limit:
                    truncated = True
                for row in rows[:edge_limit]:
                    if row["id"] in edges:
                        continue
                    unseen = {row["source"], row["target"]} - nodes.keys()
                    if len(edges) >= edge_limit or len(nodes) + len(unseen) > node_limit:
                        truncated = True
                        continue
                    edge = dict(row)
                    edge["properties"] = json.loads(edge.pop("props_json"))
                    edges[edge["id"]] = edge
                    for key in sorted(unseen):
                        nodes[key] = self.node_dict(self.db.execute(
                            "SELECT * FROM nodes WHERE id=? AND case_id=?", (key, case_id)).fetchone())
                        hops[key] = hop
                        following.append(key)
            frontier = following
        for key, node in nodes.items():
            node["hop"] = hops[key]
        return {"center": node_id, "case_id": case_id, "depth": depth,
                "nodes": list(nodes.values()), "edges": list(edges.values()),
                "truncated": truncated, "limits": {"nodes": node_limit, "edges": edge_limit},
                "scope": scope, "include_structure": bool(include_structure),
                "meaning": "Shared references and recorded relationships; not proof of causation."}
