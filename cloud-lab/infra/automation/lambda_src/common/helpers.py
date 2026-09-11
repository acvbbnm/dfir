"""공통 유틸리티 — S3, DynamoDB, 로깅, 에러 처리."""

import json
import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any

import boto3

logger = logging.getLogger("ea")
logger.setLevel(logging.INFO)

PROJECT = os.environ.get("PROJECT", "ea")
REGION = os.environ.get("REGION", "ap-northeast-2")
CASES_TABLE = os.environ.get("CASES_TABLE", f"{PROJECT}-cases")
DEDUP_TABLE = os.environ.get("DEDUP_TABLE", f"{PROJECT}-dedup")
STAGING_BUCKET = os.environ.get("STAGING_BUCKET", "")
FINAL_BUCKET = os.environ.get("FINAL_BUCKET", "")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def s3_put_json(bucket: str, key: str, obj: Any, s3_client=None) -> dict:
    s3 = s3_client or boto3.client("s3", region_name=REGION)
    body = json.dumps(obj, ensure_ascii=False, default=str)
    return s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=body.encode("utf-8"),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=os.environ["EVIDENCE_KMS_KEY_ARN"],
    )


def s3_get_json(bucket: str, key: str, s3_client=None) -> Any:
    s3 = s3_client or boto3.client("s3", region_name=REGION)
    resp = s3.get_object(Bucket=bucket, Key=key)
    return json.loads(resp["Body"].read())


def ddb_put_if_absent(table_name: str, item: dict, pk_name: str = "dedup_key") -> bool:
    ddb = boto3.resource("dynamodb", region_name=REGION)
    table = ddb.Table(table_name)
    try:
        table.put_item(
            Item=item,
            ConditionExpression=f"attribute_not_exists({pk_name})",
        )
        return True
    except ddb.meta.client.exceptions.ConditionalCheckFailedException:
        return False


def update_case_status(case_id: str, status: str, extra: dict | None = None):
    ddb = boto3.resource("dynamodb", region_name=REGION)
    table = ddb.Table(CASES_TABLE)
    update_expr = "SET #s = :status, updated_at = :now"
    expr_values = {":status": status, ":now": now_iso()}
    expr_names = {"#s": "status"}

    if extra:
        for k, v in extra.items():
            update_expr += f", {k} = :{k}"
            expr_values[f":{k}"] = v

    table.update_item(
        Key={"case_id": case_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )
