import csv
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from dfir_graph.model import sha256_file, timestamp
from dfir_graph.neo4j_io import export_graph
from dfir_graph.pipeline import ingest
from dfir_graph.store import Store

EVTX = ["EventId", "Provider", "Channel", "Computer", "Payload", "SourceFile", "TimeCreated", "EventRecordId", "ProcessId"]
PF = ["ExecutableName", "SourceFilename", "LastRun", "RunCount", "FilesLoaded", "Hash", "Volume0Serial", "PreviousRun0", "ParsingError"]


def payload(**values):
    return json.dumps({"EventData": {"Data": [{"@Name": k, "#text": v} for k, v in values.items()]}})


def event(event_id="4688", provider="Microsoft-Windows-Security-Auditing", **data):
    return {"EventId": event_id, "Provider": provider, "Channel": "Security", "Computer": "LAB",
            "Payload": payload(**data), "SourceFile": "E:\\C\\Windows\\System32\\winevt\\Logs\\Security.evtx",
            "TimeCreated": "2026-08-01 01:02:03.1234567", "EventRecordId": "42", "ProcessId": "4"}


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fields)
        writer.writeheader()
        writer.writerows(rows)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.input = self.root / "input"
        self.input.mkdir()
        self.db = self.root / "staging.sqlite"

    def tearDown(self):
        self.temp.cleanup()

    def seed(self):
        write_csv(self.input / "events.csv", EVTX, [event(NewProcessId="0x100", NewProcessName="C:\\Temp\\a.exe",
                  ProcessId="0x50", ParentProcessName="C:\\Windows\\explorer.exe", SubjectUserSid="S-1-5-21-1000",
                  CommandLine='a.exe "line1\nline2"')])
        write_csv(self.input / "prefetch.csv", PF, [{"ExecutableName": "A.EXE", "SourceFilename": "E:\\C\\Windows\\Prefetch\\A.pf",
                  "LastRun": "2026-08-01 01:02:03", "PreviousRun0": "2026-07-31 01:00:00", "Hash": "DEADBEEF",
                  "Volume0Serial": "AABB", "RunCount": "2", "ParsingError": "False"}])

    def test_repeat_import_preserves_sources_and_multiline_records(self):
        self.seed()
        hashes = {p.name: sha256_file(p) for p in self.input.iterdir()}
        first = ingest(self.input, self.db, "case1")
        second = ingest(self.input, self.db, "case1")
        self.assertEqual(first["files_failed"], 0)
        self.assertEqual(second["files_unchanged"], 2)
        for key in ("records", "nodes", "edges", "issues"):
            self.assertEqual(first["statistics"][key], second["statistics"][key])
        self.assertEqual(hashes, {p.name: sha256_file(p) for p in self.input.iterdir()})
        store = Store(self.db, readonly=True)
        try:
            evidence_id = store.db.execute("SELECT id FROM records WHERE kind='process_creation'").fetchone()[0]
            evidence = store.evidence(evidence_id)
            self.assertEqual(evidence["ordinal"], 1)
            self.assertIn("line1\\nline2", evidence["raw"]["Payload"])
            self.assertEqual(evidence["sha256"], hashes["events.csv"])
            self.assertEqual(store.db.execute("SELECT count(*) FROM edges WHERE evidence_id IS NOT NULL AND evidence_id NOT IN (SELECT id FROM records)").fetchone()[0], 0)
        finally:
            store.close()

    def test_event_identity_pid_semantics_and_unresolved_parent(self):
        self.seed()
        ingest(self.input, self.db, "case1")
        store = Store(self.db, readonly=True)
        try:
            process = store.search(label="ProcessInstance")[0]
            self.assertEqual(process["properties"]["pid"], 256)  # not CSV ProcessId=4, not parent 80
            parent = store.search(label="ProcessReference")[0]
            self.assertEqual(parent["properties"]["pid"], 80)
            self.assertFalse(parent["properties"]["resolved"])
            self.assertEqual(store.stats()["nodes"]["ProcessInstance"], 1)
        finally:
            store.close()

    def test_provider_collision_is_not_a_security_logon(self):
        write_csv(self.input / "events.csv", EVTX, [event("4625", "Microsoft-Windows-EventSystem", TargetUserSid="S-1-5-18")])
        result = ingest(self.input, self.db, "case1")
        self.assertEqual(result["statistics"]["records"], {"evtx_other": 1})
        self.assertNotIn("Observation", result["statistics"]["nodes"])

    def test_prefetch_snapshot_and_error_rows_and_derived_timeline(self):
        self.seed()
        rows = [{"ExecutableName": "A.EXE", "SourceFilename": f"E:\\{scope}\\Windows\\Prefetch\\A.pf",
                 "LastRun": "2026-08-01 01:02:03", "RunCount": "1", "Hash": "SAME", "ParsingError": error}
                for scope, error in (("C", "False"), ("VSS2", "False"), ("C", "True"))]
        write_csv(self.input / "prefetch.csv", PF, rows)
        write_csv(self.input / "timeline.csv", ["RunTime", "ExecutableName"], [{"RunTime": "2026-08-01", "ExecutableName": "A.EXE"}])
        result = ingest(self.input, self.db, "case1")
        self.assertEqual(result["statistics"]["records"]["prefetch"], 3)
        self.assertEqual(result["statistics"]["issues"]["prefetch_parsing_error"], 1)
        self.assertEqual(result["statistics"]["sources"]["derived"], 1)
        store = Store(self.db, readonly=True)
        try:
            observations = [n for n in store.search(label="Observation") if n["properties"]["kind"] == "prefetch_execution_time"]
            self.assertEqual({n["properties"]["scope"] for n in observations}, {"C", "VSS2"})
            self.assertEqual(len(observations), 2)
        finally:
            store.close()

    def test_interrupted_file_rolls_back_and_can_resume(self):
        self.seed()
        from dfir_graph import pipeline
        handler = pipeline.ingest_evtx
        def interrupt(*args):
            handler(*args)
            raise OSError("simulated read failure")
        with patch.object(pipeline, "ingest_evtx", interrupt):
            failed = ingest(self.input, self.db, "case1")
        self.assertEqual(failed["files_failed"], 1)
        self.assertNotIn("process_creation", failed["statistics"]["records"])
        result = ingest(self.input, self.db, "case1")
        self.assertEqual(result["files_failed"], 0)
        self.assertEqual(result["statistics"]["records"]["process_creation"], 1)
        self.assertNotIn("ingest_failed", result["statistics"]["issues"])

    def test_changed_interpretation_requires_a_new_case(self):
        self.seed()
        ingest(self.input, self.db, "one")
        with self.assertRaisesRegex(ValueError, "interpretation changed"):
            ingest(self.input, self.db, "one", time_zone="+09:00")
        result = ingest(self.input, self.db, "two", time_zone="+09:00")
        self.assertEqual(result["files_failed"], 0)

    def test_evidence_output_paths_rejected(self):
        self.seed()
        with self.assertRaises(ValueError):
            ingest(self.input, self.input / "db.sqlite", "case1")
        ingest(self.input, self.db, "case1")
        with self.assertRaises(ValueError):
            export_graph(self.db, self.input / "export")

    def test_unknown_time_zone_and_submicrosecond_precision(self):
        self.assertEqual(timestamp("2026-08-01 01:00:00", "unknown")["time_status"], "timezone_unknown")
        value = timestamp("2026-08-01 01:00:00.1234567", "+09:00")
        self.assertTrue(value["submicrosecond_truncated"])
        self.assertEqual(value["time_raw"], "2026-08-01 01:00:00.1234567")
        self.assertTrue(value["time_utc"].startswith("2026-07-31T16:"))

    def test_json_export_graph_endpoints_and_case_isolation(self):
        self.seed()
        ingest(self.input, self.db, "one")
        ingest(self.input, self.db, "two")
        result = export_graph(self.db, self.root / "export")
        nodes = [json.loads(line) for line in (self.root / "export/nodes.jsonl").read_text(encoding="utf-8").splitlines()]
        edges = [json.loads(line) for line in (self.root / "export/edges.jsonl").read_text(encoding="utf-8").splitlines()]
        by_id = {n["id"]: n for n in nodes}
        self.assertEqual(result["nodes"], len(nodes))
        for edge in edges:
            self.assertEqual(by_id[edge["source"]]["properties"]["case_id"], by_id[edge["target"]]["properties"]["case_id"])
        self.assertEqual({n["properties"]["case_id"] for n in nodes}, {"one", "two"})


if __name__ == "__main__":
    unittest.main()
