"""Sigma rule matching against Evidence Atlas records.

Matches are detection candidates, not attack confirmations (design principle 2).
Each match records basis="sigma_rule:{rule_id}" for analyst review.

Supported logsource categories mapped to EA record kinds:
  process_creation        → process_creation  (EventId 4688)
  ps_script               → powershell_scriptblock (EventId 4104)
  windows/security 4624   → logon_success
  windows/security 4625   → logon_failure
"""

import fnmatch
import json
import re
import sqlite3
from pathlib import Path

import yaml

from .model import uid

DETECTIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS detections (
    id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL REFERENCES records(id),
    rule_id TEXT NOT NULL,
    rule_title TEXT NOT NULL,
    rule_level TEXT NOT NULL,
    rule_file TEXT NOT NULL,
    matched_fields TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    basis TEXT NOT NULL DEFAULT 'sigma_match'
);
CREATE INDEX IF NOT EXISTS detections_record ON detections(record_id);
CREATE INDEX IF NOT EXISTS detections_rule ON detections(rule_id);
CREATE INDEX IF NOT EXISTS detections_level ON detections(rule_level);
"""

# EA record kind → Sigma logsource mapping
LOGSOURCE_MAP = {
    "process_creation": {"category": "process_creation", "product": "windows"},
    "powershell_scriptblock": {"category": "ps_script", "product": "windows"},
    "logon_success": {"product": "windows", "service": "security"},
    "logon_failure": {"product": "windows", "service": "security"},
}

# EA record kind → applicable EventIds for service-based rules
KIND_EVENT_IDS = {
    "logon_success": "4624",
    "logon_failure": "4625",
    "process_creation": "4688",
    "powershell_scriptblock": "4104",
}


def _field_map_process_creation(raw, event_data):
    """Map EA raw record fields to Sigma process_creation field names."""
    return {
        "Image": event_data.get("NewProcessName", ""),
        "OriginalFileName": event_data.get("OriginalFileName", ""),
        "CommandLine": event_data.get("CommandLine", ""),
        "ParentImage": event_data.get("ParentProcessName", ""),
        "ParentCommandLine": event_data.get("ParentProcessCommandLine", ""),
        "User": event_data.get("SubjectUserName", ""),
        "SubjectUserName": event_data.get("SubjectUserName", ""),
        "SubjectUserSid": event_data.get("SubjectUserSid", ""),
        "TargetUserName": event_data.get("TargetUserName", ""),
        "NewProcessName": event_data.get("NewProcessName", ""),
        "NewProcessId": event_data.get("NewProcessId", ""),
        "ProcessId": event_data.get("ProcessId", ""),
        "Computer": raw.get("Computer", ""),
        "IntegrityLevel": event_data.get("MandatoryLabel", ""),
        "LogonId": event_data.get("SubjectLogonId", ""),
    }


def _field_map_logon(raw, event_data):
    """Map EA raw record fields to Sigma security logon field names."""
    return {
        "EventID": raw.get("EventId", ""),
        "TargetUserName": event_data.get("TargetUserName", ""),
        "TargetUserSid": event_data.get("TargetUserSid", ""),
        "TargetDomainName": event_data.get("TargetDomainName", ""),
        "SubjectUserName": event_data.get("SubjectUserName", ""),
        "SubjectUserSid": event_data.get("SubjectUserSid", ""),
        "LogonType": event_data.get("LogonType", ""),
        "IpAddress": event_data.get("IpAddress", ""),
        "IpPort": event_data.get("IpPort", ""),
        "Status": event_data.get("Status", ""),
        "SubStatus": event_data.get("SubStatus", ""),
        "WorkstationName": event_data.get("WorkstationName", ""),
        "Computer": raw.get("Computer", ""),
        "LogonProcessName": event_data.get("LogonProcessName", ""),
        "AuthenticationPackageName": event_data.get("AuthenticationPackageName", ""),
    }


def _field_map_powershell(raw, event_data):
    """Map EA raw record fields to Sigma ps_script field names."""
    return {
        "ScriptBlockText": event_data.get("ScriptBlockText", ""),
        "ScriptBlockId": event_data.get("ScriptBlockId", ""),
        "Path": event_data.get("Path", ""),
        "Computer": raw.get("Computer", ""),
    }


def _parse_event_data(raw):
    """Extract EventData from raw EVTX record, same logic as es_mappings."""
    from .adapters import event_data
    try:
        return event_data(raw.get("Payload"))
    except (ValueError, TypeError, AttributeError):
        return {}


def _build_field_map(kind, raw):
    ed = _parse_event_data(raw)
    if kind == "process_creation":
        return _field_map_process_creation(raw, ed)
    if kind in ("logon_success", "logon_failure"):
        return _field_map_logon(raw, ed)
    if kind == "powershell_scriptblock":
        return _field_map_powershell(raw, ed)
    return {}


# ── Sigma condition evaluator ────────────────────────────────────────

def _sigma_value_match(field_value, sigma_value, modifiers):
    """Check if a single field value matches a single Sigma detection value."""
    if field_value is None:
        field_value = ""
    field_value = str(field_value)
    sigma_str = str(sigma_value)

    case_insensitive = True
    if case_insensitive:
        field_value = field_value.lower()
        sigma_str = sigma_str.lower()

    if "endswith" in modifiers:
        return field_value.endswith(sigma_str)
    if "startswith" in modifiers:
        return field_value.startswith(sigma_str)
    if "contains" in modifiers:
        return sigma_str in field_value
    if "re" in modifiers:
        try:
            return bool(re.search(sigma_str, field_value, re.IGNORECASE))
        except re.error:
            return False
    if "cidr" in modifiers:
        return False

    if "*" in sigma_str or "?" in sigma_str:
        return fnmatch.fnmatch(field_value, sigma_str)

    return field_value == sigma_str


def _parse_modifiers(field_spec):
    """Split 'FieldName|endswith|contains' into (field, [modifiers])."""
    parts = field_spec.split("|")
    return parts[0], parts[1:]


def _eval_detection_item(item, fields):
    """Evaluate one named detection block (e.g., selection_img).

    A detection item is a dict or list of dicts. Each dict's keys are field
    specs; all keys in a dict must match (AND). Multiple dicts in a list are
    OR'd. A field with a list of values is OR'd across those values.
    """
    if isinstance(item, list):
        return any(_eval_single_dict(d, fields) for d in item if isinstance(d, dict))
    if isinstance(item, dict):
        return _eval_single_dict(item, fields)
    return False


def _eval_single_dict(d, fields):
    """All field conditions in this dict must match (AND)."""
    for field_spec, expected in d.items():
        field_name, modifiers = _parse_modifiers(field_spec)
        actual = fields.get(field_name, "")
        if isinstance(expected, list):
            if not any(_sigma_value_match(actual, v, modifiers) for v in expected):
                return False
        elif isinstance(expected, (int, float)):
            if not _sigma_value_match(actual, str(expected), modifiers):
                return False
        elif expected is None:
            if actual:
                return False
        else:
            if not _sigma_value_match(actual, expected, modifiers):
                return False
    return True


def _eval_condition(condition_str, detections, fields):
    """Evaluate a Sigma condition expression against resolved detection blocks.

    Supports: and, or, not, 1 of pattern_*, all of pattern_*, parentheses.
    """
    named = {}
    for name, item in detections.items():
        if name == "condition":
            continue
        named[name] = _eval_detection_item(item, fields)

    def resolve_of(quantifier, pattern):
        pattern_re = pattern.replace("*", ".*")
        matching = [v for k, v in named.items() if re.fullmatch(pattern_re, k)]
        if not matching:
            return False
        if quantifier == "all":
            return all(matching)
        if quantifier == "1":
            return any(matching)
        return any(matching)

    tokens = _tokenize_condition(condition_str)
    result = _parse_expr(tokens, named, resolve_of)
    return result


def _tokenize_condition(condition_str):
    tokens = []
    for part in re.findall(r"\(|\)|not|and|or|all\s+of\s+\S+|1\s+of\s+\S+|\w[\w*]*", condition_str):
        tokens.append(part.strip())
    return tokens


def _parse_expr(tokens, named, resolve_of):
    """Recursive descent: expr = term ((and|or) term)*"""
    if not tokens:
        return False
    result = _parse_term(tokens, named, resolve_of)
    while tokens:
        if tokens[0] == "and":
            tokens.pop(0)
            right = _parse_term(tokens, named, resolve_of)
            result = result and right
        elif tokens[0] == "or":
            tokens.pop(0)
            right = _parse_term(tokens, named, resolve_of)
            result = result or right
        else:
            break
    return result


def _parse_term(tokens, named, resolve_of):
    """term = 'not' term | '(' expr ')' | quantifier_of | named_ref"""
    if not tokens:
        return False
    if tokens[0] == "not":
        tokens.pop(0)
        return not _parse_term(tokens, named, resolve_of)
    if tokens[0] == "(":
        tokens.pop(0)
        result = _parse_expr(tokens, named, resolve_of)
        if tokens and tokens[0] == ")":
            tokens.pop(0)
        return result
    token = tokens.pop(0)
    m = re.match(r"(all|1)\s+of\s+(\S+)", token)
    if m:
        return resolve_of(m.group(1), m.group(2))
    return named.get(token, False)


# ── Rule loading ─────────────────────────────────────────────────────

class SigmaRule:
    __slots__ = ("id", "title", "level", "logsource", "detection",
                 "tags", "status", "file_path")

    def __init__(self, data, file_path=""):
        self.id = data.get("id", "")
        self.title = data.get("title", "unknown")
        self.level = data.get("level", "unknown")
        self.logsource = data.get("logsource", {})
        self.detection = data.get("detection", {})
        self.tags = data.get("tags", [])
        self.status = data.get("status", "")
        self.file_path = str(file_path)

    @property
    def condition(self):
        c = self.detection.get("condition", "")
        return c[0] if isinstance(c, list) else c


def load_rules(rules_dir, categories=None, services=None):
    """Load Sigma YAML rules from a directory tree.

    Filter by logsource category and/or service to avoid loading irrelevant rules.
    """
    rules_dir = Path(rules_dir)
    if not rules_dir.is_dir():
        raise ValueError(f"Sigma rules directory not found: {rules_dir}")
    loaded = []
    for yml in sorted(rules_dir.rglob("*.yml")):
        try:
            data = yaml.safe_load(yml.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            continue
        if not isinstance(data, dict) or "detection" not in data:
            continue
        ls = data.get("logsource", {})
        cat = ls.get("category", "")
        svc = ls.get("service", "")
        prod = ls.get("product", "")
        if prod and prod != "windows":
            continue
        if categories and cat and cat not in categories:
            continue
        if services and svc and svc not in services:
            continue
        loaded.append(SigmaRule(data, yml.relative_to(rules_dir)))
    return loaded


def _rules_for_kind(rules_by_category, rules_by_service, kind):
    """Select applicable rules for an EA record kind."""
    ls = LOGSOURCE_MAP.get(kind)
    if not ls:
        return []
    cat = ls.get("category", "")
    svc = ls.get("service", "")
    result = []
    if cat and cat in rules_by_category:
        result.extend(rules_by_category[cat])
    if svc and svc in rules_by_service:
        result.extend(rules_by_service[svc])
    return result


def _rule_applies_to_event(rule, kind):
    """Check logsource-level EventID filter for service-based rules."""
    if rule.logsource.get("category"):
        return True
    expected_eid = KIND_EVENT_IDS.get(kind)
    if not expected_eid:
        return True
    det = rule.detection
    for name, block in det.items():
        if name == "condition":
            continue
        if isinstance(block, dict) and "EventID" in block:
            eids = block["EventID"]
            if isinstance(eids, list):
                return expected_eid in [str(e) for e in eids]
            return str(eids) == expected_eid
        if isinstance(block, list):
            for d in block:
                if isinstance(d, dict) and "EventID" in d:
                    eids = d["EventID"]
                    if isinstance(eids, list):
                        return expected_eid in [str(e) for e in eids]
                    return str(eids) == expected_eid
    return True


# ── Main scan ────────────────────────────────────────────────────────

def scan(db_path, rules_dir, case_id=None, progress=None):
    """Scan SQLite records against Sigma rules. Returns detection counts."""
    progress = progress or (lambda msg: None)

    rules = load_rules(
        rules_dir,
        categories={"process_creation", "ps_script"},
        services={"security"},
    )
    progress(f"Loaded {len(rules)} Sigma rules")

    rules_by_category = {}
    rules_by_service = {}
    for r in rules:
        cat = r.logsource.get("category", "")
        svc = r.logsource.get("service", "")
        if cat:
            rules_by_category.setdefault(cat, []).append(r)
        if svc:
            rules_by_service.setdefault(svc, []).append(r)

    db_path = Path(db_path).resolve()
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=5000")
    db.executescript(DETECTIONS_SCHEMA)
    db.commit()

    kinds = list(LOGSOURCE_MAP.keys())
    where = ",".join("?" for _ in kinds)
    sql = f"""SELECT r.* FROM records r
              JOIN sources s ON s.id = r.source_id
              WHERE r.kind IN ({where})"""
    args = list(kinds)
    if case_id:
        sql += " AND s.case_id = ?"
        args.append(case_id)

    total_records = 0
    total_detections = 0
    detection_rows = []
    batch_size = 500

    cursor = db.execute(sql, args)
    for row in cursor:
        total_records += 1
        kind = row["kind"]
        raw = json.loads(row["raw_json"])
        fields = _build_field_map(kind, raw)
        applicable = _rules_for_kind(rules_by_category, rules_by_service, kind)

        for rule in applicable:
            if not _rule_applies_to_event(rule, kind):
                continue
            try:
                if not _eval_condition(rule.condition, rule.detection, fields):
                    continue
            except Exception:
                continue

            matched = _matched_fields(rule.detection, fields)
            det_id = uid("detection", row["id"], rule.id)
            detection_rows.append((
                det_id, row["id"], rule.id, rule.title, rule.level,
                rule.file_path, json.dumps(matched, ensure_ascii=False),
                json.dumps(rule.tags or [], ensure_ascii=False),
                f"sigma_rule:{rule.id}",
            ))
            total_detections += 1

            if len(detection_rows) >= batch_size:
                _flush_detections(db, detection_rows)
                detection_rows = []

        if total_records % 5000 == 0:
            progress(f"  scanned {total_records:,} records, {total_detections:,} detections so far")

    if detection_rows:
        _flush_detections(db, detection_rows)

    db.commit()
    db.close()
    progress(f"Done: {total_records:,} records scanned, {total_detections:,} detections")
    return {"records_scanned": total_records, "detections": total_detections}


def _flush_detections(db, rows):
    db.executemany(
        "INSERT OR IGNORE INTO detections VALUES (?,?,?,?,?,?,?,?,?)",
        rows,
    )
    db.commit()


def _matched_fields(detection, fields):
    """Return field names that contributed to a match (for analyst review)."""
    matched = {}
    for name, item in detection.items():
        if name == "condition":
            continue
        if name.startswith("filter"):
            continue
        if isinstance(item, dict):
            for field_spec in item:
                fname, _ = _parse_modifiers(field_spec)
                if fname in fields and fields[fname]:
                    matched[fname] = str(fields[fname])[:200]
        elif isinstance(item, list):
            for d in item:
                if isinstance(d, dict):
                    for field_spec in d:
                        fname, _ = _parse_modifiers(field_spec)
                        if fname in fields and fields[fname]:
                            matched[fname] = str(fields[fname])[:200]
    return matched


# ── Query helpers ────────────────────────────────────────────────────

def list_detections(db_path, case_id=None, level=None, rule_id=None, limit=100):
    """Query detections from SQLite for viewer/CLI."""
    db = sqlite3.connect(Path(db_path).resolve())
    db.row_factory = sqlite3.Row
    sql = """SELECT d.*, r.kind, r.host, r.time_utc, r.time_raw
             FROM detections d
             JOIN records r ON r.id = d.record_id
             JOIN sources s ON s.id = r.source_id
             WHERE 1=1"""
    args = []
    if case_id:
        sql += " AND s.case_id = ?"
        args.append(case_id)
    if level:
        sql += " AND d.rule_level = ?"
        args.append(level)
    if rule_id:
        sql += " AND d.rule_id = ?"
        args.append(rule_id)
    sql += " ORDER BY r.time_utc DESC, d.id LIMIT ?"
    args.append(min(max(limit, 1), 500))
    rows = [dict(r) for r in db.execute(sql, args)]
    db.close()
    return rows


def detection_stats(db_path, case_id=None):
    """Aggregate detection counts by level and rule."""
    db = sqlite3.connect(Path(db_path).resolve())
    db.row_factory = sqlite3.Row
    base = "FROM detections d JOIN records r ON r.id=d.record_id JOIN sources s ON s.id=r.source_id"
    case_filter = ""
    args = []
    if case_id:
        case_filter = " AND s.case_id=?"
        args = [case_id]

    by_level = {}
    for row in db.execute(f"SELECT d.rule_level, count(*) as cnt {base} WHERE 1=1{case_filter} GROUP BY d.rule_level", args):
        by_level[row["rule_level"]] = row["cnt"]

    by_rule = []
    for row in db.execute(
        f"SELECT d.rule_id, d.rule_title, d.rule_level, count(*) as cnt {base} WHERE 1=1{case_filter} GROUP BY d.rule_id ORDER BY cnt DESC LIMIT 50",
        args
    ):
        by_rule.append(dict(row))

    total = sum(by_level.values())
    db.close()
    return {"total": total, "by_level": by_level, "by_rule": by_rule}
