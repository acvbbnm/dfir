"""Portable JSONL export and additive, parameterized Neo4j projection."""

import json
import os
from pathlib import Path

from .model import dumps
from .store import Store

LABELS = {"Case", "EvidenceSource", "Host", "Snapshot", "Observation", "ProcessInstance",
          "ProcessReference", "FilePath", "Account", "IPAddress", "ScriptBlock", "ExecutableReference",
          "AmcacheEntry", "ArtifactEntry", "ProgramReference"}
RELATIONS = {"HAS_SOURCE", "CONTAINS_OBSERVATION", "OBSERVED_IN", "OF_HOST", "RECORDS_CREATION",
             "IMAGE_PATH", "REQUESTED_CREATION", "REPORTED_TARGET_ACCOUNT", "REPORTED_PARENT",
             "REPORTED_IMAGE_PATH", "REPORTED_ACCOUNT", "REPORTED_SOURCE_ADDRESS",
             "RECORDS_SCRIPT_FRAGMENT", "REPORTED_SCRIPT_PATH", "RECORDS_EXECUTION_TIME",
             "RECORDS_AMCACHE_ENTRY", "AMCACHE_PATH", "RECORDS_SHIMCACHE",
             "RECORDS_BAM_EXECUTION", "BAM_ACCOUNT", "RECORDS_USERASSIST",
             "REPORTED_TARGET", "RECORDS_LINK_METADATA"}


def node_row(row):
    return {"id": row["id"], "label": row["label"], "properties": {
        **json.loads(row["props_json"]), "dfir_id": row["id"], "case_id": row["case_id"],
        "display": row["display"], "kind_label": row["label"], "properties_json": row["props_json"]}}


def edge_row(row):
    return {"id": row["id"], "source": row["source"], "target": row["target"], "type": row["type"],
            "properties": {**json.loads(row["props_json"]), "dfir_id": row["id"],
                           "case_id": row["case_id"], "evidence_id": row["evidence_id"], "basis": row["basis"],
                           "properties_json": row["props_json"]}}


def export_graph(database, destination):
    store = Store(database, readonly=True)
    destination = Path(destination).resolve()
    # Never let an export overwrite evidence, including unsupported files.
    for row in store.db.execute("SELECT DISTINCT root FROM imports"):
        root = Path(row[0]).resolve()
        if destination == root or root in destination.parents:
            store.close()
            raise ValueError("Export must be outside the input evidence directory")
    destination.mkdir(parents=True, exist_ok=True)
    counts = {}
    try:
        for table, converter in (("nodes", node_row), ("edges", edge_row)):
            target = destination / (table + ".jsonl")
            temporary = destination / (table + ".jsonl.tmp")
            count = 0
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                for row in store.db.execute("SELECT * FROM " + table + " ORDER BY id"):
                    stream.write(dumps(converter(row)) + "\n")
                    count += 1
            temporary.replace(target)
            counts[table] = count
        (destination / "summary.json").write_text(json.dumps(store.stats(), ensure_ascii=False, indent=2), encoding="utf-8")
        return {"directory": str(destination), **counts}
    finally:
        store.close()


def load_graph(database, uri="bolt://127.0.0.1:17687", username="neo4j", password=None,
               database_name="neo4j", batch_size=1000, progress=None):
    if not 1 <= batch_size <= 10000:
        raise ValueError("batch_size must be between 1 and 10000")
    password = password or os.environ.get("NEO4J_PASSWORD")
    if not password:
        raise ValueError("Set NEO4J_PASSWORD or use the local runtime configuration")
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise ValueError("Install the optional dependency: python -m pip install -r requirements.txt") from exc
    progress = progress or (lambda message: None)
    store = Store(database, readonly=True)
    counts = {"nodes": 0, "edges": 0}
    try:
        with GraphDatabase.driver(uri, auth=(username, password), connection_timeout=10) as driver:
            driver.verify_connectivity()
            with driver.session(database=database_name) as session:
                session.run("CREATE CONSTRAINT dfir_node_id IF NOT EXISTS FOR (n:DFIRNode) REQUIRE n.dfir_id IS UNIQUE").consume()
                for label in sorted(LABELS):
                    cursor = store.db.execute("SELECT * FROM nodes WHERE label=? ORDER BY id", (label,))
                    while rows := cursor.fetchmany(batch_size):
                        data = [node_row(row) for row in rows]
                        session.execute_write(lambda tx, batch=data, label=label: tx.run(
                            "UNWIND $rows AS row MERGE (n:DFIRNode {dfir_id:row.id}) SET n:" + label + " SET n += row.properties",
                            rows=batch).consume())
                        counts["nodes"] += len(data)
                    progress(f"Neo4j nodes: {label}; cumulative {counts['nodes']:,}")
                for kind in sorted(RELATIONS):
                    cursor = store.db.execute("SELECT * FROM edges WHERE type=? ORDER BY id", (kind,))
                    while rows := cursor.fetchmany(batch_size):
                        data = [edge_row(row) for row in rows]
                        def write_edges(tx, batch=data, kind=kind):
                            record = tx.run("UNWIND $rows AS row MATCH (a:DFIRNode {dfir_id:row.source}) "
                                            "MATCH (b:DFIRNode {dfir_id:row.target}) "
                                            "MERGE (a)-[r:" + kind + " {dfir_id:row.id}]->(b) "
                                            "SET r += row.properties RETURN count(r) AS count", rows=batch).single()
                            if record["count"] != len(batch):
                                raise ValueError("Neo4j edge endpoint missing; batch rolled back")
                        session.execute_write(write_edges)
                        counts["edges"] += len(data)
                    progress(f"Neo4j edges: {kind}; cumulative {counts['edges']:,}")
                expected_nodes = store.db.execute("SELECT count(*) FROM nodes").fetchone()[0]
                expected_edges = store.db.execute("SELECT count(*) FROM edges").fetchone()[0]
                if counts != {"nodes": expected_nodes, "edges": expected_edges}:
                    raise ValueError("Unknown graph label/relation; projection is incomplete")
        return {"uri": uri, "database": database_name, **counts}
    finally:
        store.close()
