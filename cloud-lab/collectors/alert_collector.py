"""경보 수집기 — ES Security 경보 폴링 → EventBridge 발행."""

import json
import logging
import os
import sys
import time
from pathlib import Path

import boto3
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ea-alert-collector")

ES_URL = os.environ.get("ES_URL", "http://localhost:9200")
ES_API_KEY = os.environ.get("ES_API_KEY", "")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))
EVENT_BUS = os.environ.get("EVENT_BUS", "ea-security-events")
SECURITY_ACCOUNT_ID = os.environ.get("SECURITY_ACCOUNT_ID", "")
REGION = os.environ.get("REGION", "ap-northeast-2")
CURSOR_FILE = os.environ.get("CURSOR_FILE", "/var/lib/ea-collector/cursor.json")


def load_cursor() -> list:
    path = Path(CURSOR_FILE)
    if path.exists():
        data = json.loads(path.read_text())
        return data.get("search_after", [])
    return []


def save_cursor(search_after: list):
    path = Path(CURSOR_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"search_after": search_after}))


def fetch_alerts(search_after: list) -> tuple[list, list]:
    headers = {"Content-Type": "application/json"}
    if ES_API_KEY:
        headers["Authorization"] = f"ApiKey {ES_API_KEY}"

    body = {
        "size": 100,
        "sort": [{"@timestamp": "asc"}, {"_id": "asc"}],
        "query": {
            "bool": {
                "must_not": [
                    {"term": {"kibana.alert.workflow_status": "closed"}}
                ]
            }
        },
    }

    if search_after:
        body["search_after"] = search_after

    resp = requests.post(
        f"{ES_URL}/.alerts-security.alerts-default/_search",
        headers=headers,
        json=body,
        timeout=30,
    )
    resp.raise_for_status()

    data = resp.json()
    hits = data.get("hits", {}).get("hits", [])

    new_cursor = search_after
    if hits:
        new_cursor = hits[-1]["sort"]

    return hits, new_cursor


def alert_to_event(hit: dict) -> dict:
    source = hit["_source"]
    rule = source.get("kibana.alert.rule", {})
    signal = source.get("signal", source.get("kibana.alert.original_event", {}))

    target_type = "unknown"
    instance_id = None
    ip = None

    host = source.get("host", {})
    if host.get("id"):
        instance_id = host["id"]
        target_type = "ec2"
    if host.get("ip"):
        ip = host["ip"][0] if isinstance(host["ip"], list) else host["ip"]

    return {
        "Source": "evidence-atlas.alert-collector",
        "DetailType": "SecurityAlertCollected",
        "EventBusName": EVENT_BUS,
        "Detail": json.dumps({
            "schema_version": "1.0",
            "alert_id": hit["_id"],
            "rule_id": rule.get("uuid", ""),
            "rule_name": rule.get("name", "unknown"),
            "space_id": "default",
            "severity": rule.get("severity", source.get("event.severity", "medium")),
            "detected_at": source.get("@timestamp", ""),
            "source_indices": rule.get("parameters", {}).get("index", []),
            "target": {
                "type": target_type,
                "instance_id": instance_id,
                "ip": ip,
                "role_arn": None,
                "rds_id": None,
            },
            "signal_fields": {
                k: v for k, v in source.items()
                if k in ("source.ip", "destination.ip", "url.path", "process.name", "event.action")
            },
            "collector": {
                "host": os.uname().nodename,
                "cursor": str(hit["sort"]),
                "collected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        }),
    }


def publish_events(entries: list[dict]):
    if not entries:
        return

    events = boto3.client("events", region_name=REGION)

    for i in range(0, len(entries), 10):
        batch = entries[i : i + 10]
        resp = events.put_events(Entries=batch)
        failed = resp.get("FailedEntryCount", 0)
        if failed:
            logger.warning("Failed to publish %d events", failed)


def run_once():
    cursor = load_cursor()
    hits, new_cursor = fetch_alerts(cursor)

    if not hits:
        logger.debug("No new alerts")
        return

    logger.info("Fetched %d alerts", len(hits))
    entries = [alert_to_event(h) for h in hits]
    publish_events(entries)
    save_cursor(new_cursor)
    logger.info("Published %d events, cursor updated", len(entries))


def main():
    logger.info("Alert collector started (interval=%ds)", POLL_INTERVAL)
    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            logger.info("Shutting down")
            sys.exit(0)
        except Exception:
            logger.exception("Poll cycle error")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
