import argparse
import json
import sys
from pathlib import Path

from .pipeline import ingest
from .store import Store


def main(argv=None):
    parser = argparse.ArgumentParser(description="KAPE module outputs → evidence staging → Neo4j graph")
    parser.add_argument("--db", default="data/evidence.sqlite", help="SQLite staging database outside the input folder")
    commands = parser.add_subparsers(dest="command", required=True)
    imp = commands.add_parser("ingest", help="Read-only import of KAPE CSV results")
    imp.add_argument("input")
    imp.add_argument("--case", required=True)
    imp.add_argument("--host", help="Explicit endpoint identity for artifacts without Computer")
    imp.add_argument("--time-zone", default="UTC", help="Assumption for timezone-less export values: UTC, unknown, or +09:00")
    commands.add_parser("stats")
    search = commands.add_parser("search")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--label")
    search.add_argument("--limit", type=int, default=20)
    graph = commands.add_parser("neighbors")
    graph.add_argument("id")
    graph.add_argument("--limit", type=int, default=40)
    evidence = commands.add_parser("evidence")
    evidence.add_argument("id")
    analysis = commands.add_parser('analyze', help='Evidence brief; optionally ask an installed local Ollama model')
    analysis.add_argument('id', help='Timeline observation identifier')
    analysis.add_argument('--model', help='Installed local Ollama model; no downloads or paid APIs')
    analysis.add_argument('--markdown', action='store_true', help='Print a Markdown investigation memo')
    export = commands.add_parser("export")
    export.add_argument("destination", nargs="?", default="data/export")
    load = commands.add_parser("load-neo4j")
    load.add_argument("--uri", default="bolt://127.0.0.1:17687")
    load.add_argument("--user", default="neo4j")
    load.add_argument("--database", default="neo4j")
    load.add_argument("--batch-size", type=int, default=1000)
    load.add_argument("--local-config", help="Ignored local connection JSON written by setup_runtime.py")
    serve = commands.add_parser("serve", help="Read-only local evidence/graph viewer")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument('--ai-model', help='Enable hypotheses from an installed local Ollama model')

    sigma_scan = commands.add_parser("sigma-scan", help="Match Sigma rules against SQLite records")
    sigma_scan.add_argument("--rules", default="vendor/sigma/rules/windows", help="Sigma rules directory")
    sigma_scan.add_argument("--case", default=None, help="Scan only this case")

    sigma_stats = commands.add_parser("sigma-stats", help="Show Sigma detection statistics")
    sigma_stats.add_argument("--case", default=None)
    sigma_stats.add_argument("--level", default=None, help="Filter by level (critical/high/medium/low)")

    sigma_list = commands.add_parser("sigma-list", help="List Sigma detections")
    sigma_list.add_argument("--case", default=None)
    sigma_list.add_argument("--level", default=None)
    sigma_list.add_argument("--rule-id", default=None)
    sigma_list.add_argument("--limit", type=int, default=30)

    es_sync = commands.add_parser("es-sync", help="Push SQLite data to Elasticsearch with ECS enrichment")
    es_sync.add_argument("--case", help="Sync only this case (default: all)")
    es_sync.add_argument("--es-hosts", default=None, help="ES hosts (default: http://localhost:9200)")
    es_sync.add_argument("--es-api-key", default=None, help="ES API key")
    es_sync.add_argument("--drop", action="store_true", help="Delete existing ES indices before sync")

    es_status = commands.add_parser("es-status", help="Show Elasticsearch connection and index status")
    es_status.add_argument("--es-hosts", default=None)
    es_status.add_argument("--case", default=None, help="Show stats for this case only")

    es_search = commands.add_parser("es-search", help="Full-text search records in Elasticsearch")
    es_search.add_argument("query")
    es_search.add_argument("--case", required=True)
    es_search.add_argument("--limit", type=int, default=20)
    es_search.add_argument("--es-hosts", default=None)

    args = parser.parse_args(argv)
    progress = lambda message: print(message, file=sys.stderr, flush=True)
    try:
        if args.command == "ingest":
            result = ingest(args.input, args.db, args.case, args.host, args.time_zone, progress)
        elif args.command == 'analyze':
            from .analysis import build_brief, generate_hypotheses, markdown_report
            from .timeline import TimelineIndex
            result = build_brief(TimelineIndex(args.db), args.id)
            if args.model:
                result['ai'] = generate_hypotheses(result, args.model)
            if args.markdown:
                print(markdown_report(result))
                return 0
        elif args.command == "export":
            from .neo4j_io import export_graph
            result = export_graph(args.db, args.destination)
        elif args.command == "load-neo4j":
            from .neo4j_io import load_graph
            password = None
            if args.local_config:
                config = json.loads(Path(args.local_config).read_text(encoding="utf-8"))
                args.uri, args.user, password = config["uri"], config["user"], config["password"]
                libraries = Path(args.local_config).resolve().parent / "python-libs"
                if libraries.is_dir():
                    sys.path.insert(0, str(libraries))
            result = load_graph(args.db, args.uri, args.user, password, args.database, args.batch_size, progress)
        elif args.command == "sigma-scan":
            from .sigma_engine import scan
            result = scan(args.db, args.rules, args.case, progress)
        elif args.command == "sigma-stats":
            from .sigma_engine import detection_stats
            result = detection_stats(args.db, args.case)
        elif args.command == "sigma-list":
            from .sigma_engine import list_detections
            result = list_detections(args.db, args.case, args.level, args.rule_id, args.limit)
        elif args.command == "es-sync":
            from .es_store import ESStore
            es = ESStore(hosts=args.es_hosts, api_key=args.es_api_key)
            if not es.ping():
                print("Error: Elasticsearch에 연결할 수 없습니다", file=sys.stderr)
                return 1
            if args.drop:
                if args.case:
                    dropped = es.drop_indices(args.case)
                else:
                    store = Store(args.db, readonly=True)
                    try:
                        for row in store.db.execute("SELECT id FROM cases"):
                            dropped = es.drop_indices(row[0])
                    finally:
                        store.close()
                progress("Dropped existing indices")
            result = es.sync_from_sqlite(args.db, args.case, progress)
            es.close()
        elif args.command == "es-status":
            from .es_store import ESStore
            es = ESStore(hosts=args.es_hosts)
            if not es.ping():
                print("Error: Elasticsearch에 연결할 수 없습니다", file=sys.stderr)
                return 1
            info = es.info()
            version = info.get("version", {}).get("number", "?")
            cluster = info.get("cluster_name", "?")
            cases = es.list_cases()
            result = {"cluster": cluster, "version": version,
                      "cases": cases, "case_count": len(cases)}
            if args.case:
                result["stats"] = es.stats(args.case)
            elif cases:
                result["stats"] = es.stats()
            es.close()
        elif args.command == "es-search":
            from .es_store import ESStore
            es = ESStore(hosts=args.es_hosts)
            if not es.ping():
                print("Error: Elasticsearch에 연결할 수 없습니다", file=sys.stderr)
                return 1
            result = es.search_records(args.query, args.case, args.limit)
            es.close()
        elif args.command == "serve":
            from .viewer import serve
            serve(args.db, args.port, args.ai_model)
            return 0
        else:
            store = Store(args.db, readonly=True)
            try:
                if args.command == "stats":
                    result = store.stats()
                elif args.command == "search":
                    result = store.search(args.query, args.label, args.limit)
                elif args.command == "neighbors":
                    result = store.neighborhood(args.id, args.limit)
                else:
                    result = store.evidence(args.id)
            finally:
                store.close()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if isinstance(result, dict) and result.get("files_failed") else 0
    except (ValueError, OSError) as exc:
        print("Error: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
