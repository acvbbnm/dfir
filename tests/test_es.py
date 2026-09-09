import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from dfir_graph.es_mappings import index_name, legacy_index_name, create_indices, record_to_ecs, _parse_event_data
from dfir_graph.es_store import ESStore
from dfir_graph.store import Store


class ESTests(unittest.TestCase):
    def test_case_ids_do_not_collapse(self):
        cases = ["A_B", "a-b", "A-B", "사건", "사건2", "x"*80+"a", "x"*80+"b"]
        names = [index_name("records", c) for c in cases]
        self.assertEqual(len(set(names)), len(cases))
        self.assertTrue(all(n == n.lower() and len(n) < 255 for n in names))
        with self.assertRaises(ValueError):
            index_name("records", " ")

    def test_index_metadata_keeps_exact_case_and_legacy_names_are_not_used_for_writes(self):
        es = MagicMock(); es.indices.exists.return_value = False
        create_indices(es, "사건-A")
        self.assertEqual(es.indices.create.call_count, 5)
        for call in es.indices.create.call_args_list:
            self.assertEqual(call.kwargs["body"]["mappings"]["_meta"]["ea_case_id"], "사건-A")
            self.assertNotEqual(call.kwargs["index"], legacy_index_name("records", "사건-A"))
        es.indices.get.return_value = {"ea-records-test": {"mappings": {"_meta": {"ea_case_id": "사건-A"}}}}
        self.assertEqual(ESStore(es=es).list_cases(), ["사건-A"])

    def test_legacy_case_collision_refuses_reads(self):
        es = MagicMock(); modern = index_name("records", "A_B")
        es.indices.exists.side_effect = lambda index: index != modern
        es.count.return_value = {"count": 1}
        with self.assertRaisesRegex(ValueError, "collision"):
            ESStore(es=es)._read_index("records", "A_B")
        es.count.return_value = {"count": 0}
        self.assertEqual(ESStore(es=es)._read_index("records", "A_B"), legacy_index_name("records", "A_B"))

    def test_partial_or_incomplete_bulk_never_reports_success(self):
        es = MagicMock(); store = ESStore(es=es)
        actions = [{"index": {"_index": "test", "_id": "one"}}, {"raw": "private"}]
        for response in [{"errors": True, "items": [{"index": {"_id": "one", "status": 400, "error": {"reason": "private"}}}]}, {"errors": False, "items": []}]:
            es.bulk.return_value = response
            with self.assertRaises(ValueError) as raised:
                store._send_bulk(actions, lambda _: None)
            self.assertNotIn("private", str(raised.exception))
        es.bulk.return_value = {"errors": False, "items": [{"index": {"status": 201}}]}
        self.assertEqual(store._send_bulk(actions, lambda _: None), 1)

    def test_large_node_sync_is_batched_and_unknown_case_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"test.sqlite"; sql = Store(path)
            sql.db.execute("INSERT INTO cases VALUES ('one','one')")
            for i in range(1107):
                sql.node("one", "FilePath", str(i), str(i))
            sql.db.commit()
            es = MagicMock()
            es.bulk.side_effect = lambda body, refresh: {"errors": False, "items": [{"index": {"status": 201}} for _ in body[::2]]}
            store = ESStore(es=es)
            self.assertEqual(store._bulk_nodes(sql, "one", lambda _: None), 1107)
            self.assertEqual([len(c.kwargs["body"]) for c in es.bulk.call_args_list], [2000, 214])
            with self.assertRaisesRegex(ValueError, "Unknown SQLite case"):
                store.sync_from_sqlite(path, "missing")
            sql.close()

    def test_current_aliases_and_duplicate_payload_fields(self):
        es = MagicMock(); es.indices.update_aliases.return_value = {"acknowledged": True}
        store = ESStore(es=es); store.activate_case("one")
        actions = es.indices.update_aliases.call_args.kwargs["actions"]
        self.assertEqual(len(actions), 5)
        self.assertEqual(actions[1]["add"], {"index": index_name("records", "one"), "alias": "ea-current-records"})
        es.indices.update_aliases.return_value = {"acknowledged": False}
        with self.assertRaises(ValueError):
            store.activate_case("one")
        payload = json.dumps({"EventData": {"Data": [{"@Name": "NewProcessName", "#text": "a"}, {"@Name": "NewProcessName", "#text": "b"}]}})
        self.assertEqual(_parse_event_data(payload), {})

    def test_ecs_keeps_raw_and_timestamp_semantics(self):
        raw = {"LastModified": "2026-09-01", "TargetModified": "2025-01-01"}
        row = {"id": "r", "source_id": "s", "ordinal": 1, "raw_json": json.dumps(raw), "kind": "jumplist_entry", "time_utc": "2026-09-01T00:00:00Z", "time_raw": "2026-09-01"}
        result = record_to_ecs(row, {"adapter": "jlecmd_automatic", "case_id": "one"})
        self.assertEqual(result["ea.raw"], raw)
        self.assertEqual(result["ea.time_kind"], "destlist_entry_modified")
        for invalid in ["True", "unexpected", " True "]:
            result = record_to_ecs({**row, "kind": "prefetch", "raw_json": json.dumps({"ParsingError": invalid})})
            self.assertEqual(result["event.kind"], "pipeline_error")
            self.assertNotIn("@timestamp", result)
            self.assertNotIn("ea.time_kind", result)


if __name__ == "__main__":
    unittest.main()
