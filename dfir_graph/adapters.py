"""Adapters for EvtxECmd and PECmd exports. Source values are untrusted data."""

import json
import ntpath

from .model import dumps, meaningful, pid_number, source_scope, timestamp, uid, windows_path

# Identity/normalization contract for existing EvtxECmd and PECmd imports.
# Adding an adapter does not change the identity of already imported evidence.
ADAPTER_VERSION = "1"

REGISTRY_ADAPTERS = ("amcache_file", "appcompat_cache", "bam", "userassist")
LINK_ADAPTERS = ("lecmd", "jlecmd_automatic", "jlecmd_custom")
SRUM_ADAPTERS = ("srum_network", "srum_app")
ADAPTER_VERSIONS = {name: "3" for name in REGISTRY_ADAPTERS + LINK_ADAPTERS}
ADAPTER_VERSIONS.update({name: "1" for name in SRUM_ADAPTERS})


def classify(header):
    columns = set(header)
    if {"EventId", "Provider", "Channel", "Computer", "Payload", "SourceFile"} <= columns:
        return "evtxecmd"
    if {"ExecutableName", "SourceFilename", "LastRun", "RunCount", "FilesLoaded"} <= columns:
        return "pecmd"
    if columns == {"RunTime", "ExecutableName"}:
        return "prefetch_timeline_derived"
    if {"EntryNumber", "SequenceNumber", "ParentEntryNumber", "Created0x10", "ParentPath"} <= columns:
        return "mftecmd_mft"
    if {"UpdateTimestamp", "UpdateReasons", "EntryNumber", "SequenceNumber"} <= columns:
        return "mftecmd_usn"
    if {"FileKeyLastWriteTimestamp", "SHA1", "FullPath", "Name", "IsPeFile"} <= columns:
        return "amcache_file"
    if {"ControlSet", "CacheEntryPosition", "Path", "LastModifiedTimeUTC", "Executed"} <= columns:
        return "appcompat_cache"
    if columns == {"Program", "ExecutionTime", "BatchKeyPath", "BatchValueName"}:
        return "bam"
    if {"ProgramName", "RunCounter", "FocusCount", "LastExecuted"} <= columns:
        return "userassist"
    if {"SourceFile", "TargetCreated", "TargetModified", "LocalPath"} <= columns:
        if {"AppId", "DestListVersion", "LastModified", "EntryNumber"} <= columns:
            return "jlecmd_automatic"
        if {"AppId", "EntryName"} <= columns:
            return "jlecmd_custom"
        if "NetworkPath" in columns:
            return "lecmd"
    if {"BytesSent", "BytesRecvd", "InterfaceLuid", "ExeInfo", "Timestamp"} <= columns:
        return "srum_network"
    if {"ForegroundCycleTime", "BackgroundCycleTime", "ExeInfo", "Timestamp"} <= columns:
        return "srum_app"
    return "unsupported"


def event_data(payload):
    data = json.loads(payload or "{}")
    event = data.get("EventData", {})
    entries = event.get("Data", []) if isinstance(event, dict) else []
    if isinstance(entries, dict):
        entries = [entries]
    result = {}
    for entry in entries:
        if isinstance(entry, dict) and "@Name" in entry:
            key = entry["@Name"]
            value = entry.get("#text", "")
            if key in result:
                raise ValueError("Duplicate EventData field: " + str(key))
            result[key] = value
    return result


class Projection:
    def __init__(self, store, case_id, source_id, host, scope, record_id, source_node):
        self.store, self.case = store, case_id
        self.source_id, self.host, self.scope = source_id, host, scope
        self.record, self.source_node = record_id, source_node

    def node(self, label, identity, display, props=None):
        return self.store.node(self.case, label, identity, display, props)

    def edge(self, source, target, kind, props=None, basis="observed"):
        return self.store.edge(self.case, source, target, kind, self.record, basis, props)

    def observe(self, kind, time_value, time_zone, detail, slot="0"):
        times = timestamp(time_value, time_zone)
        obs = self.node("Observation", [self.record, slot], kind + " · " + (time_value or "time unknown"),
                        {"record_id": self.record, "kind": kind, "host": self.host, "scope": self.scope,
                         "time_kind": detail.pop("time_kind", "event_recorded"), **times, **detail})
        host_node = self.node("Host", self.host, self.host, {"host": self.host})
        snapshot = self.node("Snapshot", [self.host, self.scope], self.host + " / " + self.scope,
                             {"host": self.host, "scope": self.scope, "snapshot_time": "unknown"})
        self.edge(self.source_node, obs, "CONTAINS_OBSERVATION")
        self.edge(obs, snapshot, "OBSERVED_IN")
        self.edge(snapshot, host_node, "OF_HOST")
        if times["time_status"] in ("invalid", "timezone_unknown"):
            self.store.issue(self.case, self.source_id, self.record, "time_" + times["time_status"], time_value or "")
        return obs

    def path(self, value):
        normalized = windows_path(value)
        if not normalized:
            return None
        return self.node("FilePath", [self.host, normalized], value,
                         {"host": self.host, "normalized_path": normalized,
                          "meaning": "path reference; not file content identity"})

    def account(self, sid, name=""):
        if not meaningful(sid):
            return None
        return self.node("Account", [self.host, sid], sid,
                         {"host": self.host, "sid": sid})


def insert_record(store, source, ordinal, row, kind, host, scope, time_value, zone):
    record_id = uid("record", source["id"], ordinal)
    times = timestamp(time_value, zone)
    store.db.execute("INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?)",
                     (record_id, source["id"], ordinal, dumps(row), kind, host, scope,
                      times["time_raw"], times.get("time_utc")))
    return record_id


def ingest_evtx(store, source, ordinal, row, options):
    provider, event_id = row.get("Provider", ""), row.get("EventId", "")
    channel = row.get("Channel", "")
    host = row.get("Computer") or options.get("host") or "unresolved:" + source["id"]
    scope = source_scope(row.get("SourceFile"))
    # Event IDs are provider-specific. A 4625 from EventSystem is NOT a failed logon.
    kinds = {("Microsoft-Windows-Security-Auditing", "Security", "4624"): "logon_success",
             ("Microsoft-Windows-Security-Auditing", "Security", "4625"): "logon_failure",
             ("Microsoft-Windows-Security-Auditing", "Security", "4688"): "process_creation",
             ("Microsoft-Windows-PowerShell", "Microsoft-Windows-PowerShell/Operational", "4104"): "powershell_scriptblock",
             ("Microsoft-Windows-Sysmon", "Microsoft-Windows-Sysmon/Operational", "1"): "sysmon_process_create",
             ("Microsoft-Windows-Sysmon", "Microsoft-Windows-Sysmon/Operational", "3"): "sysmon_network_connect",
             ("Microsoft-Windows-Sysmon", "Microsoft-Windows-Sysmon/Operational", "11"): "sysmon_file_create",
             ("Microsoft-Windows-Sysmon", "Microsoft-Windows-Sysmon/Operational", "22"): "sysmon_dns_query"}
    kind = kinds.get((provider, channel, event_id), "evtx_other")
    record_id = insert_record(store, source, ordinal, row, kind, host, scope, row.get("TimeCreated"), options["time_zone"])
    if kind == "evtx_other":
        return
    try:
        data = event_data(row.get("Payload"))
    except (ValueError, TypeError, AttributeError) as exc:
        store.issue(source["case_id"], source["id"], record_id, "invalid_payload", str(exc))
        return
    project = Projection(store, source["case_id"], source["id"], host, scope, record_id, source["node_id"])
    obs = project.observe(kind, row.get("TimeCreated"), options["time_zone"],
                          {"provider": provider, "channel": channel, "event_id": event_id,
                           "event_record_id": row.get("EventRecordId", ""),
                           "artifact_path": row.get("SourceFile", "")})
    if kind == "process_creation":
        new_pid = pid_number(data.get("NewProcessId"))
        if new_pid is None or not meaningful(data.get("NewProcessName")):
            store.issue(project.case, source["id"], record_id, "missing_process_identity", "4688 requires EventData.NewProcessId and NewProcessName")
            return
        process = project.node("ProcessInstance", record_id, ntpath.basename(data["NewProcessName"]) + " · PID " + str(new_pid),
                               {"host": host, "pid": new_pid, "creation_record": record_id,
                                "created_raw": row.get("TimeCreated", ""), "scope": scope,
                                "image_path": data["NewProcessName"], "command_line": data.get("CommandLine", "")})
        project.edge(obs, process, "RECORDS_CREATION")
        path = project.path(data["NewProcessName"])
        project.edge(process, path, "IMAGE_PATH")
        creator = project.account(data.get("SubjectUserSid"))
        if creator:
            project.edge(creator, obs, "REQUESTED_CREATION", {"reported_name": data.get("SubjectUserName", ""), "logon_id": data.get("SubjectLogonId", "")})
        target = project.account(data.get("TargetUserSid"))
        if target:
            project.edge(process, target, "REPORTED_TARGET_ACCOUNT")
        parent_pid = pid_number(data.get("ProcessId"))
        if parent_pid is not None:
            parent = project.node("ProcessReference", [record_id, "parent"],
                                  (ntpath.basename(data.get("ParentProcessName") or "unknown") + " · parent PID " + str(parent_pid)),
                                  {"host": host, "pid": parent_pid, "reported_path": data.get("ParentProcessName", ""),
                                   "resolved": False, "reason": "No stable instance identifier/lifetime proof; PID reuse possible"})
            project.edge(process, parent, "REPORTED_PARENT")
            parent_path = project.path(data.get("ParentProcessName"))
            if parent_path:
                project.edge(parent, parent_path, "REPORTED_IMAGE_PATH")
            store.issue(project.case, source["id"], record_id, "unresolved_parent_instance", "Parent PID retained as a reference; not merged with another execution")
        if not meaningful(data.get("CommandLine")):
            store.issue(project.case, source["id"], record_id, "missing_command_line", "4688 command line is not present in this record")
    elif kind in ("logon_success", "logon_failure"):
        account = project.account(data.get("TargetUserSid"))
        if account:
            project.edge(obs, account, "REPORTED_ACCOUNT", {"reported_name": data.get("TargetUserName", ""),
                         "logon_id": data.get("TargetLogonId", ""), "logon_type": data.get("LogonType", "")})
        address = data.get("IpAddress")
        if meaningful(address):
            import ipaddress
            try:
                address = str(ipaddress.ip_address(address))
                ip = project.node("IPAddress", address, address, {"address": address})
                project.edge(obs, ip, "REPORTED_SOURCE_ADDRESS", {"port": data.get("IpPort", "")})
            except ValueError:
                store.issue(project.case, source["id"], record_id, "invalid_ip_address", "Logon source address could not be normalized")
    elif kind == "powershell_scriptblock":
        # A 4104 message may be one part of a script block. Never count it as a
        # complete script execution or attach it to an unrelated matching PID.
        block_id = data.get("ScriptBlockId")
        script = project.node("ScriptBlock", [host, block_id or record_id], "ScriptBlock " + str(block_id or "unknown"),
                              {"host": host, "script_block_id": block_id or "", "meaning": "logged script block, not proof of each statement executing"})
        project.edge(obs, script, "RECORDS_SCRIPT_FRAGMENT", {"part": data.get("MessageNumber", ""), "total": data.get("MessageTotal", "")})
        path = project.path(data.get("Path"))
        if path:
            project.edge(script, path, "REPORTED_SCRIPT_PATH")
    elif kind == "sysmon_process_create":
        pid = pid_number(data.get("ProcessId"))
        image = data.get("Image", "")
        if pid is None or not meaningful(image):
            store.issue(project.case, source["id"], record_id, "missing_process_identity",
                        "Sysmon EventId 1 requires ProcessId and Image")
            return
        process = project.node("ProcessInstance", record_id,
                               ntpath.basename(image) + " · PID " + str(pid),
                               {"host": host, "pid": pid, "creation_record": record_id,
                                "created_raw": row.get("TimeCreated", ""), "scope": scope,
                                "image_path": image, "command_line": data.get("CommandLine", ""),
                                "hashes": data.get("Hashes", ""),
                                "integrity_level": data.get("IntegrityLevel", ""),
                                "user": data.get("User", "")})
        project.edge(obs, process, "RECORDS_CREATION")
        path = project.path(image)
        project.edge(process, path, "IMAGE_PATH")
        parent_pid = pid_number(data.get("ParentProcessId"))
        if parent_pid is not None:
            parent = project.node("ProcessReference", [record_id, "parent"],
                                  (ntpath.basename(data.get("ParentImage") or "unknown") + " · parent PID " + str(parent_pid)),
                                  {"host": host, "pid": parent_pid, "reported_path": data.get("ParentImage", ""),
                                   "command_line": data.get("ParentCommandLine", ""),
                                   "resolved": False, "reason": "PID reuse possible; parent retained as reference"})
            project.edge(process, parent, "REPORTED_PARENT")
            parent_path = project.path(data.get("ParentImage"))
            if parent_path:
                project.edge(parent, parent_path, "REPORTED_IMAGE_PATH")
            store.issue(project.case, source["id"], record_id, "unresolved_parent_instance",
                        "Parent PID retained as a reference; not merged with another execution")
    elif kind == "sysmon_network_connect":
        import ipaddress
        image = data.get("Image", "")
        dst_ip = data.get("DestinationIp", "")
        dst_port = data.get("DestinationPort", "")
        protocol = data.get("Protocol", "")
        if meaningful(image):
            path = project.path(image)
            if path:
                project.edge(obs, path, "INITIATED_CONNECTION",
                             {"pid": data.get("ProcessId", ""), "user": data.get("User", "")})
        if meaningful(dst_ip):
            try:
                dst_addr = str(ipaddress.ip_address(dst_ip))
                dst = project.node("IPAddress", dst_addr, dst_addr, {"address": dst_addr})
                project.edge(obs, dst, "CONNECTED_TO",
                             {"port": dst_port, "protocol": protocol,
                              "hostname": data.get("DestinationHostname", "")})
            except ValueError:
                store.issue(project.case, source["id"], record_id, "invalid_ip_address",
                            "Destination address could not be normalized")
        src_ip = data.get("SourceIp", "")
        if meaningful(src_ip):
            try:
                src_addr = str(ipaddress.ip_address(src_ip))
                src = project.node("IPAddress", src_addr, src_addr, {"address": src_addr})
                project.edge(obs, src, "CONNECTION_SOURCE",
                             {"port": data.get("SourcePort", "")})
            except ValueError:
                pass
    elif kind == "sysmon_file_create":
        image = data.get("Image", "")
        target = data.get("TargetFilename", "")
        if meaningful(image):
            path = project.path(image)
            if path:
                project.edge(obs, path, "CREATION_PROCESS",
                             {"pid": data.get("ProcessId", ""), "user": data.get("User", "")})
        if meaningful(target):
            target_path = project.path(target)
            if target_path:
                project.edge(obs, target_path, "REPORTS_FILE_CREATION")
    elif kind == "sysmon_dns_query":
        image = data.get("Image", "")
        query_name = data.get("QueryName", "")
        if meaningful(image):
            path = project.path(image)
            if path:
                project.edge(obs, path, "DNS_QUERY_PROCESS",
                             {"pid": data.get("ProcessId", ""), "user": data.get("User", "")})
        if meaningful(query_name):
            dns = project.node("DNSQuery", [host, query_name], query_name,
                               {"host": host, "query_name": query_name,
                                "query_results": data.get("QueryResults", ""),
                                "meaning": "DNS lookup record; not proof of connection"})
            project.edge(obs, dns, "REPORTS_DNS_QUERY")


def ingest_prefetch(store, source, ordinal, row, options):
    host = options.get("host") or "unresolved:" + source["id"]
    scope = source_scope(row.get("SourceFilename"))
    record_id = insert_record(store, source, ordinal, row, "prefetch", host, scope, row.get("LastRun"), options["time_zone"])
    if str(row.get("ParsingError", "")).strip().lower() not in ("", "false", "0"):
        store.issue(source["case_id"], source["id"], record_id, "prefetch_parsing_error", "PECmd marked this row ParsingError; retained without execution claims")
        return
    project = Projection(store, source["case_id"], source["id"], host, scope, record_id, source["node_id"])
    if not options.get("host"):
        store.issue(project.case, source["id"], record_id, "unresolved_host", "Supply --host when the input does not identify exactly one endpoint")
    # PECmd Hash is a prefetch path hash; it is NOT SHA-1/SHA-256 file content.
    executable = project.node("ExecutableReference", [host, row.get("ExecutableName", ""), row.get("Hash", ""), row.get("Volume0Serial", "")],
                              row.get("ExecutableName") or "unknown executable",
                              {"host": host, "name": row.get("ExecutableName", ""), "prefetch_hash": row.get("Hash", ""),
                               "volume_serial": row.get("Volume0Serial", ""), "meaning": "prefetch executable reference; not a process instance or content hash"})
    for slot in ["LastRun"] + ["PreviousRun" + str(i) for i in range(7)]:
        if not meaningful(row.get(slot)):
            continue
        obs = project.observe("prefetch_execution_time", row[slot], options["time_zone"],
                              {"time_kind": "prefetch_recorded_run", "slot": slot, "run_count": row.get("RunCount", ""),
                               "artifact_path": row.get("SourceFilename", ""), "executable_name": row.get("ExecutableName", "")}, slot)
        project.edge(obs, executable, "RECORDS_EXECUTION_TIME")


# ---------------------------------------------------------------------------
# Registry-based execution evidence adapters
# ---------------------------------------------------------------------------

def artifact_scope(source, row):
    return source_scope(row.get("SourceFile")) if row.get("SourceFile") else source.get("scope", "unknown")


def program_reference(project, value):
    """Keep shell identifiers and relative names separate from absolute paths."""
    drive, tail = ntpath.splitdrive(value)
    if (drive and tail.startswith("\\")) or value.lower().startswith("\\device\\"):
        return project.path(value)
    return project.node("ProgramReference", [project.host, project.scope, value], value,
                        {"meaning": "unresolved program/shell identifier; not an absolute path"}) if value else None


def _bam_sid(batch_key_path):
    import re
    match = re.search(r"(S-1-\d+-\d+(?:-\d+)*)", batch_key_path or "")
    return match.group(1) if match else None


def ingest_amcache_file(store, source, ordinal, row, options):
    host = options.get("host") or "unresolved:" + source["id"]
    scope = artifact_scope(source, row)
    time_value = row.get("FileKeyLastWriteTimestamp")
    record_id = insert_record(store, source, ordinal, row, "amcache_file", host, scope, time_value, options["time_zone"])
    full_path = row.get("FullPath", "").strip()
    sha1 = row.get("SHA1", "").strip().lower()
    name = row.get("Name", "").strip()
    if not full_path and not sha1:
        store.issue(source["case_id"], source["id"], record_id, "amcache_no_identity",
                    "Amcache entry has neither FullPath nor SHA1")
        return
    project = Projection(store, source["case_id"], source["id"], host, scope, record_id, source["node_id"])
    entry = project.node("AmcacheEntry", record_id,
                         name or ntpath.basename(full_path) or sha1,
                         {"host": host, "sha1": sha1, "full_path": full_path, "name": name,
                          "product_name": row.get("ProductName", ""), "version": row.get("Version", ""),
                          "size": row.get("Size", ""), "link_date": row.get("LinkDate", ""),
                          "is_os_component": row.get("IsOsComponent", ""),
                          "binary_type": row.get("BinaryType", ""),
                          "meaning": "Amcache-reported hash, not independently verified or guaranteed to cover the whole file; registry write time is not execution time"})
    obs = project.observe("amcache_file", time_value, options["time_zone"],
                          {"time_kind": "amcache_key_write", "executable_name": name or ntpath.basename(full_path),
                           "sha1": sha1, "application_name": row.get("ApplicationName", "")})
    project.edge(obs, entry, "RECORDS_AMCACHE_ENTRY")
    if full_path:
        path_node = project.path(full_path)
        if path_node:
            project.edge(entry, path_node, "AMCACHE_PATH")


def ingest_appcompat(store, source, ordinal, row, options):
    host = options.get("host") or "unresolved:" + source["id"]
    scope = source_scope(row.get("SourceFile"))
    path_value = row.get("Path", "").strip()
    time_value = row.get("LastModifiedTimeUTC")
    record_id = insert_record(store, source, ordinal, row, "appcompat_cache", host, scope, time_value, "UTC")
    if not path_value:
        return
    if row.get("Duplicate", "").strip().lower() == "true":
        store.issue(source["case_id"], source["id"], record_id, "appcompat_duplicate",
                    "Duplicate ShimCache entry; retained for completeness")
    project = Projection(store, source["case_id"], source["id"], host, scope, record_id, source["node_id"])
    obs = project.observe("appcompat_cache", time_value, "UTC",
                          {"time_kind": "file_last_modified",
                           "executable_name": ntpath.basename(path_value),
                           "cache_position": row.get("CacheEntryPosition", ""),
                           "artifact_path": row.get("SourceFile", ""),
                           "meaning": "LastModifiedTimeUTC is file modification time, not execution time"})
    path_node = project.path(path_value)
    if path_node:
        project.edge(obs, path_node, "RECORDS_SHIMCACHE")


def ingest_bam(store, source, ordinal, row, options):
    host = options.get("host") or "unresolved:" + source["id"]
    scope = artifact_scope(source, row)
    time_value = row.get("ExecutionTime")
    program = row.get("Program", "").strip()
    record_id = insert_record(store, source, ordinal, row, "bam_execution", host, scope, time_value, options["time_zone"])
    if not program:
        return
    project = Projection(store, source["case_id"], source["id"], host, scope, record_id, source["node_id"])
    obs = project.observe("bam_execution", time_value, options["time_zone"],
                          {"time_kind": "bam_recorded_execution",
                           "executable_name": ntpath.basename(program),
                           "device_path": program})
    path_node = program_reference(project, program)
    if program.lower().startswith("\\device\\"):
        store.issue(project.case, source["id"], record_id, "unresolved_device_mapping",
                    "Device volume retained verbatim; no drive-letter mapping has been established")
    if path_node:
        project.edge(obs, path_node, "RECORDS_BAM_EXECUTION")
    sid = _bam_sid(row.get("BatchKeyPath"))
    account = project.account(sid)
    if account:
        project.edge(obs, account, "BAM_ACCOUNT", {"batch_key_path": row.get("BatchKeyPath", "")})


def ingest_userassist(store, source, ordinal, row, options):
    host = options.get("host") or "unresolved:" + source["id"]
    scope = artifact_scope(source, row)
    program = row.get("ProgramName", "").strip()
    time_value = row.get("LastExecuted", "").strip()
    record_id = insert_record(store, source, ordinal, row, "userassist_execution", host, scope, time_value, options["time_zone"])
    if not program or program.startswith("UEME_"):
        return
    project = Projection(store, source["case_id"], source["id"], host, scope, record_id, source["node_id"])
    run_counter = row.get("RunCounter", "")
    obs = project.observe("userassist_execution", time_value, options["time_zone"],
                          {"time_kind": "userassist_last_executed",
                           "executable_name": ntpath.basename(program),
                           "program_name": program,
                           "run_counter": run_counter,
                           "focus_count": row.get("FocusCount", ""),
                           "focus_time": row.get("FocusTime", "")})
    path_node = program_reference(project, program)
    if path_node:
        project.edge(obs, path_node, "RECORDS_USERASSIST")


def ingest_link(store, source, ordinal, row, options):
    host = options.get("host") or "unresolved:" + source["id"]
    scope = artifact_scope(source, row)
    automatic = source["adapter"] == "jlecmd_automatic"
    kind = "jumplist_entry" if source["adapter"].startswith("jlecmd") else "lnk_metadata"
    primary = "LastModified" if automatic else "SourceModified"
    record_id = insert_record(store, source, ordinal, row, kind, host, scope, row.get(primary), options["time_zone"])
    project = Projection(store, source["case_id"], source["id"], host, scope, record_id, source["node_id"])
    target = row.get("Path") or row.get("LocalPath") or row.get("NetworkPath") or row.get("TargetIDAbsolutePath") or row.get("RelativePath") or ""
    entry = project.node("ArtifactEntry", record_id, ntpath.basename(target) or kind,
                         {"record_id": record_id, "artifact_path": row.get("SourceFile", ""),
                          "target_reported": target, "app_id": row.get("AppId", ""),
                          "meaning": "shortcut/jump-list metadata; not proof of target execution or access"})
    ref = program_reference(project, target)
    if ref:
        project.edge(entry, ref, "REPORTED_TARGET")
    fields = [("CreationTime", "destlist_entry_created"), ("LastModified", "destlist_entry_modified")] if automatic else [
        ("SourceCreated", "shortcut_container_created"), ("SourceModified", "shortcut_container_modified")]
    fields += [("TargetCreated", "target_created_metadata"), ("TargetModified", "target_modified_metadata"),
               ("TargetAccessed", "target_accessed_metadata")]
    for slot, meaning in fields:
        if not meaningful(row.get(slot)):
            continue
        obs = project.observe(kind, row[slot], options["time_zone"],
                              {"time_kind": meaning, "slot": slot, "executable_name": ntpath.basename(target) or kind,
                               "artifact_path": row.get("SourceFile", ""), "target_reported": target}, slot)
        project.edge(obs, entry, "RECORDS_LINK_METADATA")


# ---------------------------------------------------------------------------
# SRUM (System Resource Usage Monitor) adapters
# ---------------------------------------------------------------------------

def ingest_srum_network(store, source, ordinal, row, options):
    host = options.get("host") or "unresolved:" + source["id"]
    scope = "C"
    time_value = row.get("Timestamp")
    record_id = insert_record(store, source, ordinal, row, "srum_network_usage", host, scope, time_value, options["time_zone"])
    exe_info = row.get("ExeInfo", "").strip()
    if not exe_info:
        return
    project = Projection(store, source["case_id"], source["id"], host, scope, record_id, source["node_id"])
    obs = project.observe("srum_network_usage", time_value, options["time_zone"],
                          {"time_kind": "srum_recorded_interval",
                           "executable_name": ntpath.basename(exe_info),
                           "bytes_sent": row.get("BytesSent", ""),
                           "bytes_received": row.get("BytesRecvd", ""),
                           "interface_type": row.get("InterfaceType", "")})
    ref = program_reference(project, exe_info)
    if ref:
        project.edge(obs, ref, "RECORDS_NETWORK_USAGE")
    sid = row.get("Sid", "")
    account = project.account(sid)
    if account:
        project.edge(obs, account, "SRUM_ACCOUNT", {"reported_name": row.get("UserName", "")})


def ingest_srum_app(store, source, ordinal, row, options):
    host = options.get("host") or "unresolved:" + source["id"]
    scope = "C"
    time_value = row.get("Timestamp")
    record_id = insert_record(store, source, ordinal, row, "srum_app_usage", host, scope, time_value, options["time_zone"])
    exe_info = row.get("ExeInfo", "").strip()
    if not exe_info:
        return
    project = Projection(store, source["case_id"], source["id"], host, scope, record_id, source["node_id"])
    obs = project.observe("srum_app_usage", time_value, options["time_zone"],
                          {"time_kind": "srum_recorded_interval",
                           "executable_name": ntpath.basename(exe_info),
                           "foreground_cycle_time": row.get("ForegroundCycleTime", ""),
                           "background_cycle_time": row.get("BackgroundCycleTime", "")})
    ref = program_reference(project, exe_info)
    if ref:
        project.edge(obs, ref, "RECORDS_APP_USAGE")
    sid = row.get("Sid", "")
    account = project.account(sid)
    if account:
        project.edge(obs, account, "SRUM_ACCOUNT", {"reported_name": row.get("UserName", "")})
