"""Chronological overview of all staged events, with explicit aggregation.

This is a read-only presentation index. It does not create causal graph edges.
Prefetch uses individual valid run-time observations, not only LastRun.
"""

from collections import Counter
from datetime import datetime
import json
import threading

from .adapters import event_data
from .store import Store

LANES = [
    {"id": "process", "name": "프로세스 생성", "color": "#4dd9c4"},
    {"id": "logon", "name": "로그온", "color": "#78a9ff"},
    {"id": "powershell", "name": "PowerShell", "color": "#c497ff"},
    {"id": "prefetch", "name": "Prefetch 실행 흔적", "color": "#efba65"},
    {"id": "registry", "name": "레지스트리 기록", "color": "#f28b82"},
    {"id": "links", "name": "바로가기 · Jump List", "color": "#80cbc4"},
    {"id": "cloud", "name": "클라우드 · Linux · 웹", "color": "#ffa875"},
    {"id": "other", "name": "기타 이벤트", "color": "#93a4b9"},
]
KINDS = {"process_creation": "process", "logon_success": "logon", "logon_failure": "logon",
         "powershell_scriptblock": "powershell", "prefetch_execution_time": "prefetch", "evtx_other": "other",
         "amcache_file": "registry", "appcompat_cache": "registry",
         "bam_execution": "registry", "userassist_execution": "registry",
         "lnk_metadata": "links", "jumplist_entry": "links"}


KINDS.update({k: "cloud" for k in ("cloud_record", "cloudtrail_event", "linux_process_snapshot",
             "waf_event", "web_request", "application_audit")})

def millis(value):
    return int(datetime.fromisoformat(value).timestamp() * 1000)


class TimelineIndex:
    def __init__(self, database):
        self.database = database
        self.items = []
        self.undated = 0
        store = Store(database, readonly=True)
        try:
            self.cases = [r[0] for r in store.db.execute("SELECT id FROM cases ORDER BY id")]
            self.source_status = store.stats()["sources"]
            process_names = {json.loads(r[0]).get("creation_record", ""): r[1]
                             for r in store.db.execute("SELECT props_json,display FROM nodes WHERE label='ProcessInstance'")}
            for row in store.db.execute("""SELECT n.id,n.case_id,n.props_json,
                    json_extract(r.raw_json,'$.Payload') AS payload
                    FROM nodes n JOIN records r ON r.id=json_extract(n.props_json,'$.record_id')
                    WHERE n.label='Observation'"""):
                p = json.loads(row["props_json"])
                kind = p["kind"]
                title = p.get("title") or process_names.get(p["record_id"], kind)
                if kind == "prefetch_execution_time":
                    title = p.get("executable_name") or "Prefetch 실행 흔적"
                elif kind == "amcache_file":
                    title = (p.get("executable_name") or "Amcache") + " · Amcache"
                elif kind == "appcompat_cache":
                    title = (p.get("executable_name") or "ShimCache") + " · ShimCache"
                elif kind == "bam_execution":
                    title = (p.get("executable_name") or "BAM") + " · BAM"
                elif kind == "userassist_execution":
                    title = (p.get("executable_name") or "UserAssist") + " · UserAssist"
                elif kind in ("lnk_metadata", "jumplist_entry"):
                    title = (p.get("executable_name") or kind) + " · " + p.get("slot", "")
                elif kind == "powershell_scriptblock":
                    title = "PowerShell 스크립트 블록 · 4104"
                elif kind in ("logon_success", "logon_failure"):
                    try:
                        data = event_data(row["payload"])
                    except (ValueError, TypeError, AttributeError):
                        data = {}
                    title = ("로그온 성공" if kind == "logon_success" else "로그온 실패")
                    if data.get("TargetUserName"):
                        title += " · " + str(data["TargetUserName"])
                    title += " · " + ("4624" if kind == "logon_success" else "4625")
                self.add(row["id"], row["case_id"], p["record_id"], row["id"], kind,
                         p.get("host"), p.get("scope"), p.get("time_utc"), p.get("time_raw"), title,
                         p.get("slot", ""), p.get("time_kind", ""))
            # Other EVTX records are included as observations on the timeline,
            # without inventing semantic Neo4j relationships for them.
            for r in store.db.execute("""SELECT r.id,s.case_id,r.host,r.scope,r.time_utc,r.time_raw,
                    json_extract(r.raw_json,'$.Provider') AS provider,
                    json_extract(r.raw_json,'$.EventId') AS event_id
                    FROM records r JOIN sources s ON s.id=r.source_id WHERE r.kind='evtx_other'"""):
                self.add(r["id"], r["case_id"], r["id"], None, "evtx_other", r["host"], r["scope"],
                         r["time_utc"], r["time_raw"], f"{r['provider']} · {r['event_id']}")
        finally:
            store.close()
        self.items.sort(key=lambda item: (item["at"], item["id"]))
        self.by_id = {item["id"]: item for item in self.items}
        self.times = [item["at"] for item in self.items]

    def add(self, item_id, case, record, node, kind, host, scope, utc, raw, title, slot="", time_kind="event_recorded"):
        if not utc:
            self.undated += 1
            return
        self.items.append({"id": item_id, "case_id": case, "record_id": record, "node_id": node,
                           "kind": kind, "lane": KINDS.get(kind, "other"), "host": host or "미확정",
                           "scope": scope or "unknown", "at": millis(utc), "time_raw": raw,
                           "title": title, "slot": slot, "time_kind": time_kind})

    def meta(self):
        return {"cases": self.cases, "lanes": LANES, "count": len(self.items), "undated": self.undated,
                "hosts": sorted({e["host"] for e in self.items}),
                "scopes": sorted({e["scope"] for e in self.items}), "sources": self.source_status,
                "start": self.times[0] if self.times else None,
                "end": self.times[-1] + 1 if self.times else None}

    def select(self, case="", host="", scope="", lanes="", q=""):
        lane_set = set(lanes.split(",")) if lanes else {lane["id"] for lane in LANES}
        words = q.casefold().split()
        return [e for e in self.items
                if (not case or e["case_id"] == case) and (not host or e["host"] == host)
                and (not scope or e["scope"] == scope) and e["lane"] in lane_set
                and all(word in (e["title"] + " " + e["host"] + " " + e["id"]).casefold() for word in words)]

    def view(self, start=None, end=None, bins=60, offset=0, limit=50, **filters):
        bins, limit, offset = min(max(int(bins), 8), 160), min(max(int(limit), 1), 200), max(int(offset), 0)
        selected = self.select(**filters)
        bounds = ([selected[0]["at"], selected[-1]["at"] + 1] if selected else
                  [self.times[0], self.times[-1] + 1] if self.times else [0, 1])
        left = int(start) if start not in (None, "") else bounds[0]
        right = int(end) if end not in (None, "") else bounds[1]
        if right <= left:
            raise ValueError("End must be later than start")
        overview = [0] * 120
        for e in selected:
            i = min(119, (e["at"] - bounds[0]) * 120 // max(bounds[1] - bounds[0], 1))
            overview[i] += 1
        visible = [e for e in selected if left <= e["at"] < right]
        grouped = {}
        for e in visible:
            b = min(bins - 1, (e["at"] - left) * bins // (right - left))
            grouped.setdefault((e["lane"], b), []).append(e)
        buckets = []
        for (lane, index), events in grouped.items():
            buckets.append({"lane": lane, "index": index, "count": len(events),
                            "first": events[0]["at"], "last": events[-1]["at"],
                            "item": events[0] if len(events) == 1 else None})
        return {"bounds": bounds, "start": left, "end": right, "bins": bins, "overview": overview,
                "total": len(selected), "count": len(visible), "lanes": dict(Counter(e["lane"] for e in visible)),
                "buckets": buckets, "items": visible[offset:offset + limit], "offset": offset, "limit": limit}

    def related(self, item_id, offset=0, limit=30, order="time"):
        item = self.by_id.get(item_id)
        if not item:
            return None
        if not item["node_id"]:
            return {"items": [], "total": 0, "entities": [], "bounds": None}
        store = Store(self.database, readonly=True)
        try:
            structural = {"Case", "Host", "Snapshot", "EvidenceSource", "Observation"}
            def neighbors(node):
                return list(store.db.execute("""SELECT n.*,e.type AS relation FROM edges e JOIN nodes n
                    ON n.id=CASE WHEN e.source=? THEN e.target ELSE e.source END
                    WHERE e.source=? OR e.target=?""", (node, node, node)))
            entities = {r["id"]: r for r in neighbors(item["node_id"]) if r["label"] not in structural}
            for r in list(entities.values()):
                if r["label"] in ("ProcessInstance", "ScriptBlock", "AmcacheEntry", "ArtifactEntry"):
                    for n in neighbors(r["id"]):
                        if n["label"] not in structural:
                            entities[n["id"]] = n
            found = {}
            priority = {"FilePath": 0, "ProcessInstance": 1, "ArtifactEntry": 1,
                        "AmcacheEntry": 1, "ScriptBlock": 1, "ExecutableReference": 1,
                        "ProgramReference": 2, "ProcessReference": 3, "IPAddress": 4, "Account": 5}
            for entity in entities.values():
                connected = neighbors(entity["id"])
                for n in list(connected):
                    if entity["label"] in ("FilePath", "ProgramReference") and n["label"] in ("ProcessInstance", "ScriptBlock", "AmcacheEntry", "ArtifactEntry"):
                        connected.extend(neighbors(n["id"]))
                for n in connected:
                    other = self.by_id.get(n["id"])
                    if other and other["id"] != item_id and other["case_id"] == item["case_id"]:
                        previous = found.get(other["id"])
                        if previous is None or priority.get(entity['label'], 9) < priority.get(previous['via_kind'], 9):
                            found[other["id"]] = {**other, "via": entity["display"], "via_kind": entity["label"]}
            key = (lambda e: (priority.get(e['via_kind'], 9), abs(e['at']-item['at']), e['at'], e['id'])) if order == 'context' else (lambda e: (e['at'], e['id']))
            events = sorted(found.values(), key=key)
            offset, limit = max(0, int(offset)), min(100, max(1, int(limit)))
            times = [e["at"] for e in events] + [item["at"]]
            return {"items": events[offset:offset + limit], "total": len(events), "offset": offset,
                    "bounds": [min(times), max(times) + 1],
                    "entities": [{"id": e["id"], "label": e["label"], "display": e["display"]} for e in entities.values()]}
        finally:
            store.close()


class TimelineCache:
    def __init__(self, database):
        self.database, self.signature, self.index = database, None, None
        self.lock = threading.Lock()

    def get(self):
        with self.lock:
            store = Store(self.database, readonly=True)
            try:
                signature = tuple(tuple(r) for r in store.db.execute(
                    "SELECT id,status,finished_at FROM imports ORDER BY started_at"))
            finally:
                store.close()
            if self.index is None or signature != self.signature:
                self.index = TimelineIndex(self.database)
                self.signature = signature
            return self.index
