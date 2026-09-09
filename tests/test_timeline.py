import tempfile
import unittest
from pathlib import Path

from dfir_graph.pipeline import ingest
from dfir_graph.timeline import TimelineIndex
from test_pipeline import EVTX, PF, event, write_csv


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.input, self.db = root / "input", root / "staging.sqlite"
        self.input.mkdir()
        rows = [event(NewProcessId="0x10", NewProcessName="C:\\a.exe")]
        rows += [event("99", "OtherProvider"), {**event("99", "OtherProvider"), "TimeCreated": "invalid"}]
        write_csv(self.input / "events.csv", EVTX, rows)
        write_csv(self.input / "prefetch.csv", PF, [
            {"ExecutableName": "A.EXE", "SourceFilename": "E:\\C\\Windows\\Prefetch\\A.pf",
             "LastRun": "2026-08-02 00:00:00", "PreviousRun0": "2026-08-01 00:00:00", "Hash": "ABC", "ParsingError": "False"},
            {"ExecutableName": "A.EXE", "SourceFilename": "E:\\VSS2\\Windows\\Prefetch\\A.pf",
             "LastRun": "2026-08-01 00:00:00", "Hash": "ABC", "ParsingError": "False"},
            {"ExecutableName": "BROKEN.EXE", "SourceFilename": "E:\\C\\bad.pf", "LastRun": "2026-08-02 00:00:00", "ParsingError": "True"}])
        ingest(self.input, self.db, "one")
        ingest(self.input, self.db, "two")
        self.index = TimelineIndex(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_all_events_counted_without_derived_prefetch_duplicates(self):
        result = self.index.view(case="one")
        self.assertEqual(result["count"], 5)  # 1 process + 1 other + 3 valid PF observations
        self.assertEqual(sum(b["count"] for b in result["buckets"]), 5)
        self.assertEqual(sum(result["overview"]), 5)
        self.assertEqual(result["lanes"]["prefetch"], 3)
        self.assertEqual(self.index.meta()["undated"], 2)

    def test_time_filter_pagination_and_case_scope(self):
        all_rows = self.index.view(case="one")["items"]
        first = self.index.view(case="one", limit=2)["items"]
        rest = self.index.view(case="one", limit=100, offset=2)["items"]
        self.assertEqual(first + rest, all_rows)
        cut = all_rows[-1]["at"]
        before = self.index.view(case="one", end=cut)
        after = self.index.view(case="one", start=cut)
        self.assertEqual(before["count"] + after["count"], len(all_rows))
        self.assertEqual(self.index.view(case="one", lanes="prefetch", scope="VSS2")["count"], 1)
        self.assertEqual(self.index.view(case="one", q="BROKEN.EXE")["count"], 0)
        self.assertEqual(self.index.view(case="one", lanes="none")["count"], 0)
        with self.assertRaises(ValueError):
            self.index.view(start=5, end=5)

    def test_shared_reference_relations_remain_case_scoped(self):
        item = self.index.view(case="one", lanes="prefetch")["items"][0]
        related = self.index.related(item["id"], limit=1)
        self.assertEqual(related["total"], 2)
        self.assertEqual(len(related["items"]), 1)
        self.assertEqual(related["items"][0]["case_id"], "one")
        self.assertEqual(related["items"][0]["via_kind"], "ExecutableReference")
        second = self.index.related(item["id"], offset=1, limit=1)
        self.assertNotEqual(second["items"][0]["id"], related["items"][0]["id"])
        raw = self.index.view(case="one", lanes="other")["items"][0]
        self.assertEqual(self.index.related(raw["id"])["total"], 0)


if __name__ == "__main__":
    unittest.main()
