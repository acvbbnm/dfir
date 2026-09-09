import json
import tempfile
import unittest
from pathlib import Path

from dfir_graph.pipeline import ingest
from dfir_graph.store import Store
from dfir_graph.timeline import TimelineIndex
from test_pipeline import EVTX, event, write_csv


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.db = root / "graph.sqlite"
        rows = [event(NewProcessId="0x10", NewProcessName="C:\\shared.exe")]
        rows.append({**rows[0], "SourceFile": "E:\\VSS2\\Security.evtx"})
        write_csv(root / "input" / "events.csv", EVTX, rows)
        ingest(root / "input", self.db, "case-A")
        ingest(root / "input", self.db, "case-B")
        self.store = Store(self.db)
        self.path = self.store.db.execute("SELECT id FROM nodes WHERE label='FilePath' AND case_id='case-A'").fetchone()[0]
        self.timeline = TimelineIndex(self.db)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_depth_scope_and_provenance(self):
        before = list(self.store.db.execute("SELECT id,raw_json FROM records ORDER BY id"))
        one = self.store.graph_neighbors(self.path, depth=1)
        two = self.store.graph_neighbors(self.path, depth=2)
        self.assertGreater(len(two["nodes"]), len(one["nodes"]))
        self.assertEqual({n["case_id"] for n in two["nodes"]}, {"case-A"})
        self.assertEqual({e["evidence_scope"] for e in two["edges"]}, {"C", "VSS2"})
        scoped = self.store.graph_neighbors(self.path, depth=2, scope="C")
        self.assertEqual({e["evidence_scope"] for e in scoped["edges"]}, {"C"})
        for edge in scoped["edges"]:
            self.assertTrue(edge["basis"])
            self.assertIsNotNone(self.store.evidence(edge["evidence_id"]))
        observations = [n for n in two["nodes"] if n["label"] == "Observation"]
        self.assertEqual(len(observations), 2)
        for node in observations:
            self.assertEqual(node["properties"]["time_kind"], "event_recorded")
            self.assertIn(node["id"], self.timeline.by_id)
        self.assertEqual(before, list(self.store.db.execute("SELECT id,raw_json FROM records ORDER BY id")))

    def test_rejects_cross_case_edges_and_wrong_case_request(self):
        foreign = self.store.db.execute("SELECT id FROM nodes WHERE case_id='case-B' LIMIT 1").fetchone()[0]
        self.store.edge("case-A", self.path, foreign, "MALFORMED_CROSS_CASE")
        result = self.store.graph_neighbors(self.path, depth=2, include_structure=True)
        self.assertNotIn(foreign, {n["id"] for n in result["nodes"]})
        self.assertFalse(any(e["type"] == "MALFORMED_CROSS_CASE" for e in result["edges"]))
        self.assertIsNone(self.store.graph_neighbors(self.path, case_id="case-B"))
        self.assertIsNone(self.store.graph_neighbors("absent"))

    def test_limits_are_explicit_and_cycles_terminate(self):
        for i in range(12):
            n = self.store.node("case-A", "FilePath", str(i), str(i))
            self.store.edge("case-A", self.path, n, "REFERENCE")
            self.store.edge("case-A", n, self.path, "REFERENCE_BACK")
        result = self.store.graph_neighbors(self.path, depth=2, node_limit=3, edge_limit=4)
        self.assertLessEqual(len(result["nodes"]), 3)
        self.assertLessEqual(len(result["edges"]), 4)
        self.assertTrue(result["truncated"])
        self.assertEqual(result, self.store.graph_neighbors(self.path, depth=2, node_limit=3, edge_limit=4))
        with self.assertRaises(ValueError):
            self.store.graph_neighbors(self.path, depth=3)

    def test_structural_hubs_are_opt_in(self):
        host = self.store.db.execute("SELECT id FROM nodes WHERE case_id='case-A' AND label='Host'").fetchone()[0]
        self.assertEqual(self.store.graph_neighbors(host)["edges"], [])
        self.assertTrue(self.store.graph_neighbors(host, include_structure=True)["edges"])


if __name__ == "__main__":
    unittest.main()
