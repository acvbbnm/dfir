"""Tests for sigma_engine: rule loading, field mapping, condition evaluation."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from dfir_graph.sigma_engine import (
    _eval_condition,
    _sigma_value_match,
    _build_field_map,
    _parse_modifiers,
    load_rules,
    scan,
    list_detections,
    detection_stats,
    SigmaRule,
    DETECTIONS_SCHEMA,
)


class TestValueMatch(unittest.TestCase):
    def test_exact(self):
        self.assertTrue(_sigma_value_match("attrib.exe", "attrib.exe", []))

    def test_exact_case_insensitive(self):
        self.assertTrue(_sigma_value_match("ATTRIB.EXE", "attrib.exe", []))

    def test_endswith(self):
        self.assertTrue(_sigma_value_match(r"C:\Windows\attrib.exe", r"\attrib.exe", ["endswith"]))
        self.assertFalse(_sigma_value_match(r"C:\Windows\cmd.exe", r"\attrib.exe", ["endswith"]))

    def test_startswith(self):
        self.assertTrue(_sigma_value_match("C:\\Windows\\System32\\cmd.exe", "c:\\windows\\", ["startswith"]))

    def test_contains(self):
        self.assertTrue(_sigma_value_match("attrib +h +s file.txt", " +h ", ["contains"]))
        self.assertFalse(_sigma_value_match("attrib +s file.txt", " +h ", ["contains"]))

    def test_wildcard(self):
        self.assertTrue(_sigma_value_match("powershell.exe", "power*.exe", []))
        self.assertFalse(_sigma_value_match("cmd.exe", "power*.exe", []))

    def test_re_modifier(self):
        self.assertTrue(_sigma_value_match("abc123def", r"\d{3}", ["re"]))

    def test_none_value(self):
        self.assertTrue(_sigma_value_match(None, "", []))


class TestParseModifiers(unittest.TestCase):
    def test_no_modifier(self):
        self.assertEqual(_parse_modifiers("Image"), ("Image", []))

    def test_single(self):
        self.assertEqual(_parse_modifiers("Image|endswith"), ("Image", ["endswith"]))

    def test_multiple(self):
        self.assertEqual(_parse_modifiers("CommandLine|contains|all"),
                         ("CommandLine", ["contains", "all"]))


class TestConditionEval(unittest.TestCase):
    def test_simple_and(self):
        detection = {
            "selection_a": {"Image|endswith": r"\cmd.exe"},
            "selection_b": {"CommandLine|contains": "/c"},
            "condition": "selection_a and selection_b",
        }
        fields = {"Image": r"C:\Windows\System32\cmd.exe", "CommandLine": "cmd.exe /c whoami"}
        self.assertTrue(_eval_condition("selection_a and selection_b", detection, fields))

    def test_simple_or(self):
        detection = {
            "selection_a": {"Image|endswith": r"\cmd.exe"},
            "selection_b": {"Image|endswith": r"\powershell.exe"},
            "condition": "selection_a or selection_b",
        }
        fields = {"Image": r"C:\Windows\System32\powershell.exe"}
        self.assertTrue(_eval_condition("selection_a or selection_b", detection, fields))

    def test_not(self):
        detection = {
            "selection": {"Image|endswith": r"\cmd.exe"},
            "filter": {"CommandLine|contains": "desktop.ini"},
            "condition": "selection and not filter",
        }
        fields = {"Image": r"C:\Windows\cmd.exe", "CommandLine": "cmd /c dir"}
        self.assertTrue(_eval_condition("selection and not filter", detection, fields))

    def test_all_of_pattern(self):
        detection = {
            "selection_img": {"Image|endswith": r"\attrib.exe"},
            "selection_cli": {"CommandLine|contains": " +h "},
            "condition": "all of selection_*",
        }
        fields = {"Image": r"C:\Windows\attrib.exe", "CommandLine": "attrib +h file.txt"}
        self.assertTrue(_eval_condition("all of selection_*", detection, fields))

    def test_1_of_pattern(self):
        detection = {
            "selection_a": {"Image|endswith": r"\cmd.exe"},
            "selection_b": {"Image|endswith": r"\powershell.exe"},
            "condition": "1 of selection_*",
        }
        fields = {"Image": r"C:\Windows\powershell.exe"}
        self.assertTrue(_eval_condition("1 of selection_*", detection, fields))

    def test_no_match(self):
        detection = {
            "selection": {"Image|endswith": r"\cmd.exe"},
            "condition": "selection",
        }
        fields = {"Image": r"C:\Windows\notepad.exe"}
        self.assertFalse(_eval_condition("selection", detection, fields))


class TestFieldMap(unittest.TestCase):
    def test_process_creation(self):
        raw = {
            "Computer": "TESTHOST",
            "Payload": json.dumps({"EventData": {"Data": [
                {"@Name": "NewProcessName", "#text": r"C:\Windows\cmd.exe"},
                {"@Name": "CommandLine", "#text": "cmd /c whoami"},
                {"@Name": "SubjectUserName", "#text": "admin"},
            ]}}),
        }
        fields = _build_field_map("process_creation", raw)
        self.assertEqual(fields["Image"], r"C:\Windows\cmd.exe")
        self.assertEqual(fields["CommandLine"], "cmd /c whoami")
        self.assertEqual(fields["User"], "admin")
        self.assertEqual(fields["Computer"], "TESTHOST")

    def test_logon(self):
        raw = {
            "EventId": "4624",
            "Computer": "DC01",
            "Payload": json.dumps({"EventData": {"Data": [
                {"@Name": "TargetUserName", "#text": "admin"},
                {"@Name": "LogonType", "#text": "3"},
                {"@Name": "IpAddress", "#text": "10.0.0.5"},
            ]}}),
        }
        fields = _build_field_map("logon_success", raw)
        self.assertEqual(fields["TargetUserName"], "admin")
        self.assertEqual(fields["LogonType"], "3")
        self.assertEqual(fields["EventID"], "4624")


class TestSigmaRuleLoad(unittest.TestCase):
    def test_load_from_yaml(self):
        data = {
            "id": "test-001",
            "title": "Test Rule",
            "level": "high",
            "logsource": {"category": "process_creation", "product": "windows"},
            "detection": {
                "selection": {"Image|endswith": r"\evil.exe"},
                "condition": "selection",
            },
            "tags": ["attack.execution"],
        }
        rule = SigmaRule(data, "test.yml")
        self.assertEqual(rule.id, "test-001")
        self.assertEqual(rule.title, "Test Rule")
        self.assertEqual(rule.level, "high")
        self.assertEqual(rule.condition, "selection")


class TestScanIntegration(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "test.sqlite"
        db = sqlite3.connect(self.db_path)
        db.executescript("""
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO meta VALUES ('schema_version', '1');
            CREATE TABLE cases (id TEXT PRIMARY KEY, name TEXT NOT NULL);
            INSERT INTO cases VALUES ('TEST', 'Test Case');
            CREATE TABLE sources (
                id TEXT PRIMARY KEY, case_id TEXT, relative_path TEXT,
                absolute_path TEXT, sha256 TEXT, bytes INTEGER,
                adapter TEXT, status TEXT, rows_count INTEGER DEFAULT 0,
                error TEXT, context_json TEXT, adapter_version TEXT);
            INSERT INTO sources VALUES ('src1', 'TEST', 'test.csv', 'C:\\test.csv',
                'abc', 100, 'evtxecmd', 'ok', 1, NULL, '{}', '1');
            CREATE TABLE records (
                id TEXT PRIMARY KEY, source_id TEXT, ordinal INTEGER,
                raw_json TEXT, kind TEXT, host TEXT, scope TEXT, time_raw TEXT, time_utc TEXT,
                UNIQUE(source_id, ordinal));
            CREATE TABLE nodes (id TEXT PRIMARY KEY, case_id TEXT, label TEXT, display TEXT, props_json TEXT);
            CREATE TABLE edges (id TEXT PRIMARY KEY, case_id TEXT, source TEXT, target TEXT, type TEXT,
                evidence_id TEXT, basis TEXT, props_json TEXT);
            CREATE TABLE issues (id TEXT PRIMARY KEY, case_id TEXT, source_id TEXT,
                record_id TEXT, code TEXT, message TEXT);
        """)
        payload = json.dumps({"EventData": {"Data": [
            {"@Name": "NewProcessName", "#text": r"C:\Windows\System32\cmd.exe"},
            {"@Name": "CommandLine", "#text": r"cmd.exe /c powershell -enc base64"},
            {"@Name": "ParentProcessName", "#text": r"C:\Windows\explorer.exe"},
            {"@Name": "SubjectUserName", "#text": "testuser"},
            {"@Name": "NewProcessId", "#text": "0x1234"},
        ]}})
        raw = json.dumps({
            "Provider": "Microsoft-Windows-Security-Auditing",
            "Channel": "Security",
            "EventId": "4688",
            "Computer": "TESTHOST",
            "Payload": payload,
        })
        db.execute("INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?)",
                   ("rec1", "src1", 1, raw, "process_creation", "TESTHOST", "C", "2024-01-01T00:00:00Z", "2024-01-01T00:00:00+00:00"))
        db.commit()
        db.close()

        self.rules_dir = Path(self.tmpdir) / "rules"
        self.rules_dir.mkdir()
        rule_yaml = """
title: Test CMD Execution
id: test-rule-001
level: high
logsource:
    category: process_creation
    product: windows
detection:
    selection:
        Image|endswith: '\\cmd.exe'
    condition: selection
tags:
    - attack.execution
"""
        (self.rules_dir / "test_rule.yml").write_text(rule_yaml, encoding="utf-8")

    def test_scan_finds_detection(self):
        result = scan(self.db_path, self.rules_dir)
        self.assertEqual(result["records_scanned"], 1)
        self.assertGreaterEqual(result["detections"], 1)

    def test_list_detections(self):
        scan(self.db_path, self.rules_dir)
        dets = list_detections(self.db_path)
        self.assertGreaterEqual(len(dets), 1)
        self.assertEqual(dets[0]["rule_title"], "Test CMD Execution")
        self.assertEqual(dets[0]["kind"], "process_creation")

    def test_detection_stats(self):
        scan(self.db_path, self.rules_dir)
        stats = detection_stats(self.db_path)
        self.assertGreaterEqual(stats["total"], 1)
        self.assertIn("high", stats["by_level"])

    def test_idempotent_scan(self):
        scan(self.db_path, self.rules_dir)
        result1 = detection_stats(self.db_path)
        scan(self.db_path, self.rules_dir)
        result2 = detection_stats(self.db_path)
        self.assertEqual(result1["total"], result2["total"])


if __name__ == "__main__":
    unittest.main()
