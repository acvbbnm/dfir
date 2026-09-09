"""Elasticsearch index mappings and ECS field conversion for Evidence Atlas.

EA fields live under the ea.* namespace alongside standard ECS fields.
The original CSV row is preserved in ea.raw (evidence integrity principle).
"""

import json
import re

def index_name(prefix, case_id):
    slug = re.sub(r"[^a-z0-9\-]", "-", case_id.lower().strip())[:80]
    return f"ea-{prefix}-{slug}"


ALL_PREFIXES = ("sources", "records", "nodes", "edges", "issues")


SOURCES_MAPPING = {
    "mappings": {
        "properties": {
            "case_id": {"type": "keyword"},
            "relative_path": {"type": "keyword"},
            "absolute_path": {"type": "keyword"},
            "sha256": {"type": "keyword"},
            "bytes": {"type": "long"},
            "adapter": {"type": "keyword"},
            "adapter_version": {"type": "keyword"},
            "status": {"type": "keyword"},
            "rows_count": {"type": "integer"},
            "error": {"type": "text"},
            "context": {"type": "object", "enabled": False},
        }
    },
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
}

RECORDS_MAPPING = {
    "mappings": {
        "properties": {
            "@timestamp": {"type": "date"},
            "event.kind": {"type": "keyword"},
            "event.category": {"type": "keyword"},
            "event.action": {"type": "keyword"},
            "event.outcome": {"type": "keyword"},
            "event.provider": {"type": "keyword"},
            "event.code": {"type": "keyword"},
            "host.name": {"type": "keyword"},
            "process.name": {"type": "keyword"},
            "process.pid": {"type": "long"},
            "process.command_line": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 1024}}},
            "process.parent.name": {"type": "keyword"},
            "process.parent.pid": {"type": "long"},
            "user.name": {"type": "keyword"},
            "user.id": {"type": "keyword"},
            "source.ip": {"type": "ip", "ignore_malformed": True},
            "source.port": {"type": "integer"},
            "ea.record_id": {"type": "keyword"},
            "ea.source_id": {"type": "keyword"},
            "ea.case_id": {"type": "keyword"},
            "ea.kind": {"type": "keyword"},
            "ea.scope": {"type": "keyword"},
            "ea.time_kind": {"type": "keyword"},
            "ea.time_raw": {"type": "keyword"},
            "ea.adapter": {"type": "keyword"},
            "ea.adapter_version": {"type": "keyword"},
            "ea.source_sha256": {"type": "keyword"},
            "ea.ordinal": {"type": "integer"},
            "ea.raw": {"type": "object", "enabled": False},
        }
    },
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
}

NODES_MAPPING = {
    "mappings": {
        "properties": {
            "case_id": {"type": "keyword"},
            "label": {"type": "keyword"},
            "display": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "props": {"type": "object", "enabled": False},
        }
    },
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
}

EDGES_MAPPING = {
    "mappings": {
        "properties": {
            "case_id": {"type": "keyword"},
            "source": {"type": "keyword"},
            "target": {"type": "keyword"},
            "type": {"type": "keyword"},
            "evidence_id": {"type": "keyword"},
            "basis": {"type": "keyword"},
            "props": {"type": "object", "enabled": False},
        }
    },
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
}

ISSUES_MAPPING = {
    "mappings": {
        "properties": {
            "case_id": {"type": "keyword"},
            "source_id": {"type": "keyword"},
            "record_id": {"type": "keyword"},
            "code": {"type": "keyword"},
            "message": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
        }
    },
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
}

INDEX_MAPPINGS = {
    "sources": SOURCES_MAPPING,
    "records": RECORDS_MAPPING,
    "nodes": NODES_MAPPING,
    "edges": EDGES_MAPPING,
    "issues": ISSUES_MAPPING,
}


def create_indices(es, case_id):
    created = []
    for prefix, mapping in INDEX_MAPPINGS.items():
        name = index_name(prefix, case_id)
        if not es.indices.exists(index=name):
            es.indices.create(index=name, body=mapping)
            created.append(name)
    return created


def delete_indices(es, case_id):
    deleted = []
    for prefix in ALL_PREFIXES:
        name = index_name(prefix, case_id)
        if es.indices.exists(index=name):
            es.indices.delete(index=name)
            deleted.append(name)
    return deleted


def _parse_event_data(payload_str):
    try:
        data = json.loads(payload_str or "{}")
        event = data.get("EventData", {})
        entries = event.get("Data", []) if isinstance(event, dict) else []
        if isinstance(entries, dict):
            entries = [entries]
        result = {}
        for entry in entries:
            if isinstance(entry, dict) and "@Name" in entry:
                result[entry["@Name"]] = entry.get("#text", "")
        return result
    except (ValueError, TypeError, AttributeError):
        return {}


def record_to_ecs(record_row, source_row=None):
    """Convert a SQLite record row + source to an ECS-enriched ES document.

    The ea.* fields preserve Evidence Atlas semantics; ECS fields provide
    Kibana/Sigma compatibility. This is additive — no EA data is lost.
    """
    raw = json.loads(record_row["raw_json"]) if isinstance(record_row["raw_json"], str) else record_row["raw_json"]
    kind = record_row["kind"]
    host = record_row.get("host") or ""

    doc = {
        "ea.record_id": record_row["id"],
        "ea.source_id": record_row["source_id"],
        "ea.kind": kind,
        "ea.scope": record_row.get("scope", "unknown"),
        "ea.time_raw": record_row.get("time_raw", ""),
        "ea.ordinal": record_row.get("ordinal", 0),
        "ea.raw": raw,
    }

    if source_row:
        doc["ea.case_id"] = source_row.get("case_id", "")
        doc["ea.adapter"] = source_row.get("adapter", "")
        doc["ea.adapter_version"] = source_row.get("adapter_version", "")
        doc["ea.source_sha256"] = source_row.get("sha256", "")

    time_utc = record_row.get("time_utc")
    if time_utc:
        doc["@timestamp"] = time_utc

    doc["host.name"] = host

    if kind == "process_creation":
        doc["event.kind"] = "event"
        doc["event.category"] = ["process"]
        doc["event.action"] = "process-created"
        doc["event.code"] = "4688"
        doc["event.provider"] = "Microsoft-Windows-Security-Auditing"
        doc["ea.time_kind"] = "event_recorded"
        ed = _parse_event_data(raw.get("Payload"))
        if ed.get("NewProcessName"):
            doc["process.name"] = ed["NewProcessName"].rsplit("\\", 1)[-1]
            doc["process.executable"] = ed["NewProcessName"]
        pid = ed.get("NewProcessId")
        if pid:
            try:
                doc["process.pid"] = int(pid, 16) if pid.lower().startswith("0x") else int(pid)
            except ValueError:
                pass
        if ed.get("CommandLine"):
            doc["process.command_line"] = ed["CommandLine"]
        if ed.get("ParentProcessName"):
            doc["process.parent.name"] = ed["ParentProcessName"].rsplit("\\", 1)[-1]
        ppid = ed.get("ProcessId")
        if ppid:
            try:
                doc["process.parent.pid"] = int(ppid, 16) if ppid.lower().startswith("0x") else int(ppid)
            except ValueError:
                pass
        if ed.get("SubjectUserName"):
            doc["user.name"] = ed["SubjectUserName"]
        if ed.get("SubjectUserSid"):
            doc["user.id"] = ed["SubjectUserSid"]

    elif kind in ("logon_success", "logon_failure"):
        doc["event.kind"] = "event"
        doc["event.category"] = ["authentication"]
        doc["event.action"] = "logon"
        doc["event.outcome"] = "success" if kind == "logon_success" else "failure"
        doc["event.code"] = "4624" if kind == "logon_success" else "4625"
        doc["event.provider"] = "Microsoft-Windows-Security-Auditing"
        doc["ea.time_kind"] = "event_recorded"
        ed = _parse_event_data(raw.get("Payload"))
        if ed.get("TargetUserName"):
            doc["user.name"] = ed["TargetUserName"]
        if ed.get("TargetUserSid"):
            doc["user.id"] = ed["TargetUserSid"]
        ip = ed.get("IpAddress")
        if ip and ip not in ("-", "::1", "127.0.0.1", ""):
            doc["source.ip"] = ip
            port = ed.get("IpPort")
            if port and port != "0":
                try:
                    doc["source.port"] = int(port)
                except ValueError:
                    pass

    elif kind == "powershell_scriptblock":
        doc["event.kind"] = "event"
        doc["event.category"] = ["process"]
        doc["event.action"] = "script-block-logged"
        doc["event.code"] = "4104"
        doc["event.provider"] = "Microsoft-Windows-PowerShell"
        doc["ea.time_kind"] = "event_recorded"

    elif kind == "evtx_other":
        doc["event.kind"] = "event"
        doc["event.provider"] = raw.get("Provider", "")
        doc["event.code"] = str(raw.get("EventId", ""))
        doc["ea.time_kind"] = "event_recorded"

    elif kind == "prefetch":
        doc["event.kind"] = "event"
        doc["event.category"] = ["process"]
        doc["event.action"] = "prefetch-recorded"
        doc["ea.time_kind"] = "prefetch_recorded_run"
        if raw.get("ExecutableName"):
            doc["process.name"] = raw["ExecutableName"]

    elif kind in ("amcache_file", "appcompat_cache", "bam_execution", "userassist_execution"):
        doc["event.kind"] = "event"
        doc["event.category"] = ["registry"]
        time_kind_map = {
            "amcache_file": "amcache_key_write",
            "appcompat_cache": "file_last_modified",
            "bam_execution": "bam_recorded_execution",
            "userassist_execution": "userassist_last_executed",
        }
        doc["ea.time_kind"] = time_kind_map.get(kind, "event_recorded")

    elif kind in ("lnk_metadata", "jumplist_entry"):
        doc["event.kind"] = "event"
        doc["event.category"] = ["file"]
        doc["ea.time_kind"] = "shortcut_container_modified"

    return doc
