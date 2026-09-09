"""Compare every projected identity/endpoint with a running local Neo4j.

Run from dfir-graph after load-neo4j. --reload also verifies repeat loading.
Only aggregate results are printed; credentials and evidence values stay local.
"""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / ".runtime" / "python-libs"))

from dfir_graph.neo4j_io import load_graph
from dfir_graph.store import Store


def verify(database, config_path, reload=False):
    from neo4j import GraphDatabase

    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    if reload:
        load_graph(database, config["uri"], config["user"], config["password"])
    store = Store(database, readonly=True)
    try:
        assert store.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "SQLite integrity failed"
        assert not store.db.execute("PRAGMA foreign_key_check").fetchall(), "Dangling staging reference"
        cases = [r[0] for r in store.db.execute("SELECT id FROM cases")]
        expected_nodes = {(r[0], r[1]) for r in store.db.execute("SELECT id,label FROM nodes")}
        expected_edges = {tuple(r) for r in store.db.execute("SELECT id,source,target,type FROM edges")}
        with GraphDatabase.driver(config["uri"], auth=(config["user"], config["password"])) as driver:
            with driver.session(database="neo4j") as session:
                nodes = list(session.run("MATCH (n:DFIRNode) WHERE n.case_id IN $cases "
                                         "RETURN n.dfir_id AS id, n.kind_label AS label", cases=cases))
                edges = list(session.run("MATCH (a:DFIRNode)-[r]->(b:DFIRNode) "
                                         "WHERE r.case_id IN $cases AND r.dfir_id IS NOT NULL "
                                         "RETURN r.dfir_id AS id,a.dfir_id AS source,b.dfir_id AS target,type(r) AS type", cases=cases))
        actual_nodes = {(r["id"], r["label"]) for r in nodes}
        actual_edges = {(r["id"], r["source"], r["target"], r["type"]) for r in edges}
        assert len(nodes) == len(actual_nodes) and expected_nodes == actual_nodes, "Neo4j nodes differ/duplicate"
        assert len(edges) == len(actual_edges) and expected_edges == actual_edges, "Neo4j edges differ/duplicate"
        return {"sqlite_integrity": "ok", "foreign_keys": "ok", "neo4j_exact_identities_and_endpoints": "ok",
                "reloaded_without_duplicates": reload, "nodes": len(nodes), "edges": len(edges)}
    finally:
        store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/sba.sqlite")
    parser.add_argument("--config", default=".runtime/connection.json")
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(args.db, args.config, args.reload), indent=2))
