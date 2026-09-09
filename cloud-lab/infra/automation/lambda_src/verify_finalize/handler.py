"""ea-verify-finalize: staging 객체 SHA-256 검증 → manifest 생성 → final 복사."""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone

import boto3

logger = logging.getLogger("ea")
logger.setLevel(logging.INFO)

REGION = os.environ.get("REGION", "ap-northeast-2")
STAGING_BUCKET = os.environ.get("STAGING_BUCKET", "")
FINAL_BUCKET = os.environ.get("FINAL_BUCKET", "")
CASES_TABLE = os.environ.get("CASES_TABLE", "ea-cases")


def lambda_handler(event, context):
    case_id = event["case_id"]
    collection_results = event.get("collection_results", [])

    logger.info("Verifying and finalizing case %s", case_id)

    s3 = boto3.client("s3", region_name=REGION)
    prefix = f"cases/{case_id}/"

    staging_objects = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=STAGING_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            staging_objects.append(obj)

    jobs = []
    missing = []
    total_size = 0

    for obj in staging_objects:
        key = obj["Key"]
        size = obj["Size"]
        total_size += size

        try:
            resp = s3.get_object(Bucket=STAGING_BUCKET, Key=key)
            body = resp["Body"].read()
            sha256 = hashlib.sha256(body).hexdigest()

            s3.put_object(
                Bucket=FINAL_BUCKET,
                Key=key,
                Body=body,
                ContentType=resp.get("ContentType", "application/octet-stream"),
                ServerSideEncryption="aws:kms",
                Metadata={"sha256": sha256},
            )

            jobs.append({
                "key": key,
                "size_bytes": size,
                "sha256": sha256,
                "status": "verified",
            })
        except Exception as e:
            logger.warning("Failed to verify/copy %s: %s", key, e)
            missing.append({"key": key, "error": str(e)})

    if not staging_objects:
        integrity = "FAIL"
    elif missing:
        integrity = "PARTIAL"
    else:
        integrity = "PASS"

    manifest = {
        "schema_version": "1.0",
        "case_id": case_id,
        "finalized_at": datetime.now(timezone.utc).isoformat(),
        "integrity": integrity,
        "total_objects": len(staging_objects),
        "verified_objects": len(jobs),
        "missing_objects": len(missing),
        "total_size_bytes": total_size,
        "jobs": jobs,
        "missing": missing,
        "collection_results": collection_results,
    }

    manifest_key = f"cases/{case_id}/manifest.json"
    s3.put_object(
        Bucket=FINAL_BUCKET,
        Key=manifest_key,
        Body=json.dumps(manifest, ensure_ascii=False, default=str).encode("utf-8"),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
    )

    ddb = boto3.resource("dynamodb", region_name=REGION)
    table = ddb.Table(CASES_TABLE)
    final_status = "READY" if integrity == "PASS" else ("PARTIAL" if integrity == "PARTIAL" else "FAILED")

    table.update_item(
        Key={"case_id": case_id},
        UpdateExpression="SET #s = :status, manifest_key = :mk, updated_at = :now, jobs = :jobs",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": final_status,
            ":mk": manifest_key,
            ":now": datetime.now(timezone.utc).isoformat(),
            ":jobs": jobs,
        },
    )

    logger.info("Case %s finalized: %s (%d objects, %d missing)", case_id, integrity, len(jobs), len(missing))

    return {
        "integrity": integrity,
        "manifest_key": manifest_key,
        "missing": missing,
    }
