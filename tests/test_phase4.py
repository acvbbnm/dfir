"""Tests for Phase 4: multi-source expansion (MFT/USN, Sysmon, SRUM)."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from dfir_graph.adapters import classify, event_data, insert_record, Projection, SRUM_ADAPTERS
from dfir_graph.sigma_engine import (
    _build_field_map, _eval_condition, LOGSOURCE_MAP, KIND_EVENT_IDS,
)


class TestClassifyNewAdapters(unittest.TestCase):
    def test_mftecmd_mft(self):
        header = ["EntryNumber", "SequenceNumber", "ParentEntryNumber", "ParentSequenceNumber",
                  "FileName", "Created0x10", "LastModified0x10", "LastRecordChange0x10",
                  "LastAccess0x10", "InUse", "IsDirectory", "ParentPath", "SourceFile"]
        self.assertEqual(classify(header), "mftecmd_mft")

    def test_mftecmd_usn(self):
        header = ["UpdateTimestamp", "UpdateReasons", "Name", "EntryNumber",
                  "SequenceNumber", "ParentEntryNumber", "ParentSequenceNumber", "SourceFile"]
        self.assertEqual(classify(header), "mftecmd_usn")

    def test_srum_network(self):
        header = ["Id", "Timestamp", "ExeInfo", "ExeInfoDescription", "ExeTimestamp",
                  "SidType", "Sid", "UserName", "InterfaceLuid", "InterfaceType",
                  "BytesSent", "BytesRecvd"]
        self.assertEqual(classify(header), "srum_network")

    def test_srum_app(self):
        header = ["Id", "Timestamp", "ExeInfo", "ExeInfoDescription", "ExeTimestamp",
                  "SidType", "Sid", "UserName", "ForegroundCycleTime", "BackgroundCycleTime",
                  "FaceTime"]
        self.assertEqual(classify(header), "srum_app")

    def test_evtxecmd_still_works(self):
        header = ["EventId", "Provider", "Channel", "Computer", "Payload",
                  "SourceFile", "TimeCreated", "EventRecordId"]
        self.assertEqual(classify(header), "evtxecmd")

    def test_srum_constants(self):
        self.assertIn("srum_network", SRUM_ADAPTERS)
        self.assertIn("srum_app", SRUM_ADAPTERS)


class TestSysmonIngest(unittest.TestCase):
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
        db.commit()
        db.close()

    def _make_sysmon_row(self, event_id, event_data_entries):
        payload = json.dumps({"EventData": {"Data": event_data_entries}})
        return {
            "Provider": "Microsoft-Windows-Sysmon",
            "Channel": "Microsoft-Windows-Sysmon/Operational",
            "EventId": str(event_id),
            "Computer": "TESTHOST",
            "Payload": payload,
            "SourceFile": "C:\\test.evtx",
            "TimeCreated": "2024-06-15T10:30:00Z",
            "EventRecordId": "1001",
        }

    def test_sysmon_process_create_kind(self):
        from dfir_graph.store import Store
        from dfir_graph.adapters import ingest_evtx
        store = Store(self.db_path)
        source = {"id": "src1", "case_id": "TEST", "node_id": "node1", "adapter": "evtxecmd", "scope": "C"}
        store.node("TEST", "EvidenceSource", "src1", "test", {})
        row = self._make_sysmon_row(1, [
            {"@Name": "ProcessId", "#text": "4567"},
            {"@Name": "Image", "#text": r"C:\Windows\System32\cmd.exe"},
            {"@Name": "CommandLine", "#text": "cmd.exe /c whoami"},
            {"@Name": "ParentImage", "#text": r"C:\Windows\explorer.exe"},
            {"@Name": "ParentProcessId", "#text": "1234"},
            {"@Name": "User", "#text": "TESTHOST\\admin"},
            {"@Name": "Hashes", "#text": "SHA256=abc123"},
            {"@Name": "IntegrityLevel", "#text": "Medium"},
        ])
        ingest_evtx(store, source, 1, row, {"host": "TESTHOST", "time_zone": "UTC"})
        record = store.db.execute("SELECT kind FROM records WHERE ordinal=1").fetchone()
        self.assertEqual(record[0], "sysmon_process_create")
        nodes = [dict(r) for r in store.db.execute("SELECT label FROM nodes WHERE label='ProcessInstance'")]
        self.assertTrue(len(nodes) >= 1)
        store.close()

    def test_sysmon_network_connect_kind(self):
        from dfir_graph.store import Store
        from dfir_graph.adapters import ingest_evtx
        store = Store(self.db_path)
        source = {"id": "src1", "case_id": "TEST", "node_id": "node1", "adapter": "evtxecmd", "scope": "C"}
        store.node("TEST", "EvidenceSource", "src1", "test", {})
        row = self._make_sysmon_row(3, [
            {"@Name": "ProcessId", "#text": "4567"},
            {"@Name": "Image", "#text": r"C:\Windows\System32\svchost.exe"},
            {"@Name": "Protocol", "#text": "tcp"},
            {"@Name": "SourceIp", "#text": "10.0.0.5"},
            {"@Name": "SourcePort", "#text": "49152"},
            {"@Name": "DestinationIp", "#text": "10.0.0.1"},
            {"@Name": "DestinationPort", "#text": "443"},
            {"@Name": "User", "#text": "NT AUTHORITY\\SYSTEM"},
        ])
        ingest_evtx(store, source, 2, row, {"host": "TESTHOST", "time_zone": "UTC"})
        record = store.db.execute("SELECT kind FROM records WHERE ordinal=2").fetchone()
        self.assertEqual(record[0], "sysmon_network_connect")
        ips = [dict(r) for r in store.db.execute("SELECT label FROM nodes WHERE label='IPAddress'")]
        self.assertTrue(len(ips) >= 1)
        store.close()

    def test_sysmon_file_create_kind(self):
        from dfir_graph.store import Store
        from dfir_graph.adapters import ingest_evtx
        store = Store(self.db_path)
        source = {"id": "src1", "case_id": "TEST", "node_id": "node1", "adapter": "evtxecmd", "scope": "C"}
        store.node("TEST", "EvidenceSource", "src1", "test", {})
        row = self._make_sysmon_row(11, [
            {"@Name": "ProcessId", "#text": "4567"},
            {"@Name": "Image", "#text": r"C:\Windows\System32\cmd.exe"},
            {"@Name": "TargetFilename", "#text": r"C:\Users\admin\malware.exe"},
            {"@Name": "User", "#text": "admin"},
        ])
        ingest_evtx(store, source, 3, row, {"host": "TESTHOST", "time_zone": "UTC"})
        record = store.db.execute("SELECT kind FROM records WHERE ordinal=3").fetchone()
        self.assertEqual(record[0], "sysmon_file_create")
        store.close()

    def test_sysmon_dns_query_kind(self):
        from dfir_graph.store import Store
        from dfir_graph.adapters import ingest_evtx
        store = Store(self.db_path)
        source = {"id": "src1", "case_id": "TEST", "node_id": "node1", "adapter": "evtxecmd", "scope": "C"}
        store.node("TEST", "EvidenceSource", "src1", "test", {})
        row = self._make_sysmon_row(22, [
            {"@Name": "ProcessId", "#text": "4567"},
            {"@Name": "Image", "#text": r"C:\Windows\System32\nslookup.exe"},
            {"@Name": "QueryName", "#text": "evil.example.com"},
            {"@Name": "QueryResults", "#text": "93.184.216.34"},
            {"@Name": "User", "#text": "admin"},
        ])
        ingest_evtx(store, source, 4, row, {"host": "TESTHOST", "time_zone": "UTC"})
        record = store.db.execute("SELECT kind FROM records WHERE ordinal=4").fetchone()
        self.assertEqual(record[0], "sysmon_dns_query")
        dns_nodes = [dict(r) for r in store.db.execute("SELECT label FROM nodes WHERE label='DNSQuery'")]
        self.assertTrue(len(dns_nodes) >= 1)
        store.close()


class TestSRUMIngest(unittest.TestCase):
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
            INSERT INTO sources VALUES ('src2', 'TEST', 'srum.csv', 'C:\\srum.csv',
                'def', 200, 'srum_network', 'ok', 1, NULL, '{}', '1');
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
        db.commit()
        db.close()

    def test_srum_network_ingest(self):
        from dfir_graph.store import Store
        from dfir_graph.adapters import ingest_srum_network
        store = Store(self.db_path)
        source = {"id": "src2", "case_id": "TEST", "node_id": "node2", "adapter": "srum_network", "scope": "C"}
        store.node("TEST", "EvidenceSource", "src2", "srum", {})
        row = {"Timestamp": "2024-06-15T12:00:00Z", "ExeInfo": r"C:\Windows\System32\svchost.exe",
               "BytesSent": "1024", "BytesRecvd": "2048", "InterfaceLuid": "12345",
               "InterfaceType": "Wifi", "Sid": "S-1-5-18", "UserName": "SYSTEM"}
        ingest_srum_network(store, source, 1, row, {"host": "TESTHOST", "time_zone": "UTC"})
        record = store.db.execute("SELECT kind FROM records WHERE ordinal=1").fetchone()
        self.assertEqual(record[0], "srum_network_usage")
        store.close()

    def test_srum_app_ingest(self):
        from dfir_graph.store import Store
        from dfir_graph.adapters import ingest_srum_app
        store = Store(self.db_path)
        source = {"id": "src2", "case_id": "TEST", "node_id": "node2", "adapter": "srum_app", "scope": "C"}
        store.node("TEST", "EvidenceSource", "src2", "srum", {})
        row = {"Timestamp": "2024-06-15T12:00:00Z", "ExeInfo": r"C:\Program Files\App\app.exe",
               "ForegroundCycleTime": "100000", "BackgroundCycleTime": "50000",
               "Sid": "S-1-5-21-123-456-789-1001", "UserName": "testuser"}
        ingest_srum_app(store, source, 1, row, {"host": "TESTHOST", "time_zone": "UTC"})
        record = store.db.execute("SELECT kind FROM records WHERE ordinal=1").fetchone()
        self.assertEqual(record[0], "srum_app_usage")
        store.close()

    def test_srum_empty_exe_skipped(self):
        from dfir_graph.store import Store
        from dfir_graph.adapters import ingest_srum_network
        store = Store(self.db_path)
        source = {"id": "src2", "case_id": "TEST", "node_id": "node2", "adapter": "srum_network", "scope": "C"}
        store.node("TEST", "EvidenceSource", "src2", "srum", {})
        row = {"Timestamp": "2024-06-15T12:00:00Z", "ExeInfo": "",
               "BytesSent": "0", "BytesRecvd": "0", "InterfaceLuid": "0",
               "InterfaceType": "", "Sid": "", "UserName": ""}
        ingest_srum_network(store, source, 1, row, {"host": "TESTHOST", "time_zone": "UTC"})
        nodes = store.db.execute("SELECT count(*) FROM nodes WHERE label='Observation'").fetchone()[0]
        self.assertEqual(nodes, 0)
        store.close()


class TestSysmonSigmaFieldMap(unittest.TestCase):
    def test_sysmon_process_creation_in_logsource_map(self):
        self.assertIn("sysmon_process_create", LOGSOURCE_MAP)
        self.assertEqual(LOGSOURCE_MAP["sysmon_process_create"]["category"], "process_creation")

    def test_sysmon_network_in_logsource_map(self):
        self.assertIn("sysmon_network_connect", LOGSOURCE_MAP)
        self.assertEqual(LOGSOURCE_MAP["sysmon_network_connect"]["category"], "network_connection")

    def test_sysmon_file_in_logsource_map(self):
        self.assertIn("sysmon_file_create", LOGSOURCE_MAP)

    def test_sysmon_dns_in_logsource_map(self):
        self.assertIn("sysmon_dns_query", LOGSOURCE_MAP)

    def test_sysmon_kind_event_ids(self):
        self.assertEqual(KIND_EVENT_IDS["sysmon_process_create"], "1")
        self.assertEqual(KIND_EVENT_IDS["sysmon_network_connect"], "3")
        self.assertEqual(KIND_EVENT_IDS["sysmon_file_create"], "11")
        self.assertEqual(KIND_EVENT_IDS["sysmon_dns_query"], "22")

    def test_sysmon_process_field_map(self):
        raw = {
            "Computer": "TESTHOST",
            "Payload": json.dumps({"EventData": {"Data": [
                {"@Name": "Image", "#text": r"C:\Windows\System32\cmd.exe"},
                {"@Name": "CommandLine", "#text": "cmd.exe /c whoami"},
                {"@Name": "ParentImage", "#text": r"C:\Windows\explorer.exe"},
                {"@Name": "User", "#text": "admin"},
                {"@Name": "Hashes", "#text": "SHA256=abc123"},
                {"@Name": "IntegrityLevel", "#text": "Medium"},
            ]}}),
        }
        fields = _build_field_map("sysmon_process_create", raw)
        self.assertEqual(fields["Image"], r"C:\Windows\System32\cmd.exe")
        self.assertEqual(fields["CommandLine"], "cmd.exe /c whoami")
        self.assertEqual(fields["ParentImage"], r"C:\Windows\explorer.exe")
        self.assertEqual(fields["User"], "admin")
        self.assertEqual(fields["Computer"], "TESTHOST")

    def test_sysmon_network_field_map(self):
        raw = {
            "Computer": "TESTHOST",
            "Payload": json.dumps({"EventData": {"Data": [
                {"@Name": "Image", "#text": r"C:\tool.exe"},
                {"@Name": "DestinationIp", "#text": "10.0.0.1"},
                {"@Name": "DestinationPort", "#text": "443"},
                {"@Name": "Protocol", "#text": "tcp"},
            ]}}),
        }
        fields = _build_field_map("sysmon_network_connect", raw)
        self.assertEqual(fields["Image"], r"C:\tool.exe")
        self.assertEqual(fields["DestinationIp"], "10.0.0.1")
        self.assertEqual(fields["DestinationPort"], "443")

    def test_sysmon_process_sigma_match(self):
        raw = {
            "Computer": "TESTHOST",
            "Payload": json.dumps({"EventData": {"Data": [
                {"@Name": "Image", "#text": r"C:\Windows\System32\cmd.exe"},
                {"@Name": "CommandLine", "#text": "cmd.exe /c whoami"},
            ]}}),
        }
        fields = _build_field_map("sysmon_process_create", raw)
        detection = {
            "selection": {"Image|endswith": "\\cmd.exe"},
            "condition": "selection",
        }
        self.assertTrue(_eval_condition("selection", detection, fields))


if __name__ == "__main__":
    unittest.main()
