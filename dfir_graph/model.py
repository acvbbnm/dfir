"""Stable identifiers and conservative normalization; no evidence is executed."""

import hashlib
import json
import ntpath
import re
from datetime import datetime, timezone


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def uid(kind, *parts):
    return kind + ":" + hashlib.sha256(dumps(parts).encode("utf-8")).hexdigest()[:32]


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def csv_encoding(path):
    with path.open("rb") as stream:
        head = stream.read(4)
    return "utf-16" if head.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"


def windows_path(value):
    """A path identity, NOT a claim that file bytes or execution are identical."""
    value = (value or "").strip().replace("/", "\\")
    if value.startswith("\\\\?\\"):
        value = value[4:]
    return ntpath.normpath(value).casefold() if value else ""


def source_scope(path):
    """Only recognize KAPE's explicit source prefix, never the analysis drive."""
    match = re.match(r"^[A-Za-z]:\\(VSS\d+|[A-Za-z])\\", (path or "").replace("/", "\\"), re.I)
    return match.group(1).upper() if match else "unknown"


def pid_number(value):
    value = str(value or "").strip()
    if not value or value == "-":
        return None
    try:
        return int(value, 16 if value.lower().startswith("0x") else 10)
    except ValueError:
        return None


def meaningful(value):
    return value is not None and str(value).strip() not in ("", "-", "S-1-0-0")


def timestamp(value, assumed_zone="UTC"):
    """Keep original precision and record the timezone assumption explicitly.

    Python datetime supports microseconds; preserve the original string (including
    100ns digits) as evidence and expose the loss in the normalized representation.
    """
    raw = (value or "").strip()
    if not raw:
        return {"time_raw": "", "time_utc": None, "time_status": "missing"}
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        assumed = parsed.tzinfo is None
        if assumed:
            if assumed_zone == "unknown":
                return {"time_raw": raw, "time_utc": None, "time_status": "timezone_unknown"}
            if assumed_zone == "UTC":
                zone = timezone.utc
            else:
                from datetime import timedelta
                match = re.fullmatch(r"([+-])(\d{2}):(\d{2})", assumed_zone)
                if not match or int(match[2]) > 14 or int(match[3]) > 59:
                    raise ValueError("Timezone must be UTC, unknown or a fixed offset such as +09:00")
                zone = timezone(timedelta(minutes=(1 if match[1] == "+" else -1) * (int(match[2]) * 60 + int(match[3]))))
            parsed = parsed.replace(tzinfo=zone)
        precision = re.search(r"\.([0-9]+)", raw)
        return {"time_raw": raw, "time_utc": parsed.astimezone(timezone.utc).isoformat(timespec="microseconds"),
                "time_status": "assumed_" + assumed_zone if assumed else "explicit_offset",
                "submicrosecond_truncated": bool(precision and len(precision[1]) > 6)}
    except ValueError:
        return {"time_raw": raw, "time_utc": None, "time_status": "invalid"}
