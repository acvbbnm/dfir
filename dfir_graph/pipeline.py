"""Streaming, file-atomic imports with content hashes and repeatable identities."""

import csv
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .adapters import (ADAPTER_VERSION, ADAPTER_VERSIONS, REGISTRY_ADAPTERS, LINK_ADAPTERS, classify,
                        ingest_evtx, ingest_prefetch,
                        ingest_amcache_file, ingest_appcompat, ingest_bam, ingest_userassist, ingest_link)
from .model import csv_encoding, dumps, sha256_file, uid, source_scope
from .store import Store

csv.field_size_limit(32 * 1024 * 1024)


def now():
    return datetime.now(timezone.utc).isoformat()


def files_under(root):
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink() and root in path.resolve().parents:
            yield path


def read_header(path):
    with path.open("r", encoding=csv_encoding(path), newline="") as stream:
        return next(csv.reader(stream), [])


def identify_host(paths):
    hosts = set()
    for path, adapter in paths:
        if adapter != "evtxecmd":
            continue
        with path.open("r", encoding=csv_encoding(path), newline="") as stream:
            for row in csv.DictReader(stream):
                if row.get("Computer"):
                    hosts.add(row["Computer"])
    return next(iter(hosts)) if len(hosts) == 1 else None


def registry_origins(paths, root):
    """Resolve detail exports only through RECmd's explicit PluginDetailFile.

    Never open paths supplied inside evidence. A unique basename allows a copied
    result directory to retain its mapping; conflicting hives stay unresolved.
    """
    import ntpath
    candidates = {}
    counts = {}
    for path, _ in paths:
        counts[path.name.casefold()] = counts.get(path.name.casefold(), 0) + 1
    for path, _ in paths:
        if path.suffix.lower() != ".csv":
            continue
        try:
            if not {"HivePath", "PluginDetailFile"} <= set(read_header(path)):
                continue
            with path.open(encoding=csv_encoding(path), newline="") as stream:
                for ordinal, row in enumerate(csv.DictReader(stream), 1):
                    name = ntpath.basename(row.get("PluginDetailFile") or "").casefold()
                    hive = row.get("HivePath")
                    if name and hive and counts.get(name) == 1:
                        candidates.setdefault(name, {}).setdefault(hive, {
                            "hive_path": hive, "scope": source_scope(hive),
                            "mapping_source": path.relative_to(root).as_posix(), "mapping_ordinal": ordinal,
                            "method": "recmd_plugin_detail_reference"})
        except (UnicodeError, csv.Error):
            continue
    return {name: next(iter(hives.values())) for name, hives in candidates.items() if len(hives) == 1}


def ingest(root, database, case_id, host=None, time_zone="UTC", progress=None):
    root, database = Path(root).resolve(), Path(database).resolve()
    if not root.is_dir():
        raise ValueError("Input must be an existing directory of KAPE module outputs")
    if database == root or root in database.parents:
        raise ValueError("Staging database must be outside the evidence directory")
    if not case_id.strip():
        raise ValueError("Case identifier must not be empty")
    if time_zone not in ("UTC", "unknown"):
        import re
        match = re.fullmatch(r"([+-])(\d{2}):(\d{2})", time_zone)
        if not match or int(match[2]) > 14 or int(match[3]) > 59:
            raise ValueError("Invalid timezone; use UTC, unknown or +09:00")
    progress = progress or (lambda message: None)
    paths = []
    for path in files_under(root):
        adapter = "metadata" if path.suffix.lower() == ".txt" else "unsupported"
        if path.suffix.lower() == ".csv":
            try:
                header = read_header(path)
                adapter = classify(header) if len(header) == len(set(header)) else "invalid_header"
            except (UnicodeError, csv.Error):
                adapter = "invalid_header"
        paths.append((path, adapter))
    progress("Scanning host metadata in EvtxECmd exports")
    inferred_host = host or identify_host(paths)
    origins = registry_origins(paths, root)
    options = {"host": inferred_host, "time_zone": time_zone, "adapter_version": ADAPTER_VERSION}
    store = Store(database)
    run_id = str(uuid.uuid4())
    imported, skipped, failed = 0, 0, 0
    try:
        previous_options = store.db.execute(
            "SELECT DISTINCT options_json FROM imports WHERE case_id=? AND root=?",
            (case_id, str(root))).fetchall()
        if any(json.loads(row[0]) != options for row in previous_options):
            raise ValueError("Import interpretation changed for this case/input. Use a new case or database for different host/timezone/adapter settings")
        store.db.execute("INSERT OR IGNORE INTO cases VALUES (?,?)", (case_id, case_id))
        store.db.execute("INSERT INTO imports VALUES (?,?,?,?,?,?,?)", (run_id, case_id, str(root), now(), None, "running", dumps(options)))
        case_node = store.node(case_id, "Case", case_id, case_id)
        store.db.commit()
        for position, (path, adapter) in enumerate(paths, 1):
            relative = path.relative_to(root).as_posix()
            # Hash all inputs, including unsupported data, to make the inventory
            # auditable. No original artifact or input file is modified.
            before = path.stat()
            digest = sha256_file(path)
            source_id = uid("source", case_id, str(root), relative, digest, options)
            previous = store.db.execute("SELECT status,adapter_version FROM sources WHERE id=?", (source_id,)).fetchone()
            adapter_version = ADAPTER_VERSIONS.get(adapter, ADAPTER_VERSION)
            context = {"input_root": str(root), "host_assignment": inferred_host,
                       "host_assignment_method": "explicit" if host else "single_computer_in_evtx" if inferred_host else "unresolved",
                       "time_zone_assumption": time_zone, "source_type": "parser_export",
                       "original_artifact_hash_verified": False}
            origin = origins.get(path.name.casefold(), {})
            if origin:
                context["registry_origin"] = origin
            store.db.execute("""INSERT OR IGNORE INTO sources
                (id,case_id,relative_path,absolute_path,sha256,bytes,adapter,status,context_json,adapter_version)
                VALUES (?,?,?,?,?,?,?,'pending',?,?)""",
                (source_id, case_id, relative, str(path), digest, before.st_size, adapter, dumps(context), adapter_version))
            store.db.execute("INSERT OR IGNORE INTO import_sources VALUES (?,?)", (run_id, source_id))
            store.db.commit()
            newly_supported = previous and previous[0] == "unsupported" and adapter != "unsupported"
            if previous and previous[0] == "complete" and previous[1] != adapter_version:
                raise ValueError("An already parsed adapter changed interpretation; use a new case or database")
            if previous and previous[0] in ("complete", "unsupported", "derived", "metadata") and not newly_supported:
                skipped += 1
                continue
            progress(f"[{position}/{len(paths)}] {adapter}: {relative}")
            source_node = None
            try:
                with store.db:
                    source_node = store.node(case_id, "EvidenceSource", source_id, relative,
                                             {"source_id": source_id, "sha256": digest, "relative_path": relative, "adapter": adapter})
                    store.edge(case_id, case_node, source_node, "HAS_SOURCE", props={"source_id": source_id})
                    # Previously inventoried unsupported files can now be parsed
                    # without replacing any existing records or source IDs.
                    store.db.execute("UPDATE sources SET adapter=?,adapter_version=?,context_json=? WHERE id=?",
                                     (adapter, adapter_version, dumps(context), source_id))
                    if newly_supported:
                        store.db.execute("UPDATE nodes SET props_json=? WHERE id=?",
                                         (dumps({"source_id": source_id, "sha256": digest, "relative_path": relative, "adapter": adapter}), source_node))
                    source = {"id": source_id, "case_id": case_id, "node_id": source_node,
                              "adapter": adapter, "scope": origin.get("scope", "unknown")}
                    count = 0
                    registry_handlers = {"amcache_file": ingest_amcache_file, "appcompat_cache": ingest_appcompat,
                                         "bam": ingest_bam, "userassist": ingest_userassist}
                    if adapter in ("evtxecmd", "pecmd") + REGISTRY_ADAPTERS + LINK_ADAPTERS:
                        handler = (ingest_evtx if adapter == "evtxecmd" else
                                   ingest_prefetch if adapter == "pecmd" else
                                   ingest_link if adapter in LINK_ADAPTERS else registry_handlers[adapter])
                        with path.open("r", encoding=csv_encoding(path), newline="") as stream:
                            for ordinal, row in enumerate(csv.DictReader(stream, strict=True), 1):
                                if None in row or any(value is None for value in row.values()):
                                    raise ValueError(f"CSV column mismatch at logical record {ordinal}")
                                handler(store, source, ordinal, row, options)
                                count += 1
                                if count % 25000 == 0:
                                    progress(f"  staged {count:,} records")
                        status = "complete"
                    elif adapter == "metadata":
                        status = "metadata"
                        # Only parse tool-status lines, never execute commands in logs.
                        if "consolelog" in path.name.lower():
                            with path.open("r", encoding=csv_encoding(path), errors="replace") as stream:
                                for line_number, line in enumerate(stream, 1):
                                    if "| E |" in line or "not found" in line.lower() or "error processing file" in line.lower():
                                        store.issue(case_id, source_id, None, "upstream_tool_error", f"Line {line_number}: {line.strip()[:500]}")
                    elif adapter == "prefetch_timeline_derived":
                        status = "derived"
                        store.issue(case_id, source_id, None, "derived_timeline_not_imported", "Use PECmd base output to preserve source and avoid duplicate execution observations")
                    elif adapter == "invalid_header":
                        raise ValueError("CSV encoding/header could not be recognized")
                    else:
                        status = "unsupported"
                    after = path.stat()
                    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns or (status == "complete" and sha256_file(path) != digest):
                        raise ValueError("Input changed during ingestion; file transaction rolled back")
                    store.db.execute("UPDATE sources SET status=?,rows_count=?,error=NULL WHERE id=?", (status, count, source_id))
                    store.db.execute("DELETE FROM issues WHERE source_id=? AND code='ingest_failed'", (source_id,))
                imported += 1
            except (ValueError, UnicodeError, csv.Error, OSError, json.JSONDecodeError) as exc:
                # The file transaction rolled back. Other sources remain usable;
                # a later invocation retries only incomplete/failed inputs.
                with store.db:
                    store.db.execute("UPDATE sources SET status='failed',error=? WHERE id=?", (str(exc), source_id))
                    store.issue(case_id, source_id, None, "ingest_failed", str(exc))
                failed += 1
                progress("  FAILED: " + str(exc))
        with store.db:
            store.db.execute("UPDATE imports SET status=?,finished_at=? WHERE id=?", ("partial" if failed else "complete", now(), run_id))
        return {"run_id": run_id, "files_seen": len(paths), "files_processed": imported,
                "files_unchanged": skipped, "files_failed": failed, "assigned_host": inferred_host, "statistics": store.stats()}
    except BaseException:
        store.db.rollback()
        with store.db:
            store.db.execute("UPDATE imports SET status='interrupted',finished_at=? WHERE id=?", (now(), run_id))
        raise
    finally:
        store.close()
