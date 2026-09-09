"""ea-collect-aws-logs: CloudTrail LookupEvents + 관련 S3 원본 참조 → staging 저장."""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3

logger = logging.getLogger("ea")
logger.setLevel(logging.INFO)

REGION = os.environ.get("REGION", "ap-northeast-2")
STAGING_BUCKET = os.environ.get("STAGING_BUCKET", "")


def lambda_handler(event, context):
    case_id = event["case_id"]
    target = event["target"]
    window_minutes = event.get("time_window_minutes", 15)

    logger.info("Collecting AWS logs for case %s (±%d min)", case_id, window_minutes)

    detected_at = event.get("trigger", {}).get("detected_at")
    if detected_at:
        center = datetime.fromisoformat(detected_at.replace("Z", "+00:00"))
    else:
        center = datetime.now(timezone.utc)

    start_time = center - timedelta(minutes=window_minutes)
    end_time = center + timedelta(minutes=window_minutes)

    sources = {}

    ct = boto3.client("cloudtrail", region_name=REGION)
    events = []
    kwargs = {
        "StartTime": start_time,
        "EndTime": end_time,
        "MaxResults": 50,
    }

    if target.get("instance_id"):
        kwargs["LookupAttributes"] = [
            {"AttributeKey": "ResourceName", "AttributeValue": target["instance_id"]}
        ]

    try:
        paginator = ct.get_paginator("lookup_events")
        for page in paginator.paginate(**kwargs):
            for evt in page.get("Events", []):
                events.append({
                    "EventId": evt["EventId"],
                    "EventName": evt["EventName"],
                    "EventTime": evt["EventTime"].isoformat(),
                    "Username": evt.get("Username", ""),
                    "CloudTrailEvent": json.loads(evt.get("CloudTrailEvent", "{}")),
                })

        sources["cloudtrail"] = {"count": len(events), "start": start_time.isoformat(), "end": end_time.isoformat()}
    except Exception as e:
        logger.warning("CloudTrail lookup error: %s", e)
        sources["cloudtrail"] = {"count": 0, "error": str(e)}

    s3 = boto3.client("s3", region_name=REGION)

    if events:
        s3.put_object(
            Bucket=STAGING_BUCKET,
            Key=f"cases/{case_id}/aws-logs/cloudtrail-events.json",
            Body=json.dumps(events, ensure_ascii=False, default=str).encode("utf-8"),
            ContentType="application/json",
            ServerSideEncryption="aws:kms",
        )

    metadata = {
        "case_id": case_id,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "time_window": {"start": start_time.isoformat(), "end": end_time.isoformat()},
        "sources": sources,
    }

    s3.put_object(
        Bucket=STAGING_BUCKET,
        Key=f"cases/{case_id}/aws-logs/collection-metadata.json",
        Body=json.dumps(metadata, ensure_ascii=False, default=str).encode("utf-8"),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
    )

    logger.info("Collected %d CloudTrail events", len(events))
    return {"sources": sources}
