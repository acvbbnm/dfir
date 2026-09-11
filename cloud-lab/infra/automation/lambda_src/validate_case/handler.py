"""ea-validate-case: 사건 입력 검증, DynamoDB 중복 확인, 대상 허용 확인."""

import logging
import re
import os
import time

import boto3

logger = logging.getLogger("ea")
logger.setLevel(logging.INFO)

DEDUP_TABLE = os.environ.get("DEDUP_TABLE", "ea-dedup")
CASES_TABLE = os.environ.get("CASES_TABLE", "ea-cases")
REGION = os.environ.get("REGION", "ap-northeast-2")


def lambda_handler(event, context):
    case_id = event["case_id"]
    trigger = event["trigger"]
    target = event["target"]

    logger.info("Validating case %s", case_id)

    if not trigger.get("alert_id") or not trigger.get("rule_name"):
        return {"status": "INVALID", "reason": "missing trigger fields"}

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", case_id):
        return {"status": "INVALID", "reason": "invalid case ID"}
    if target.get("type") not in {"ec2", "rds", "iam", "s3"}:
        return {"status": "INVALID", "reason": "unsupported target type"}
    if target.get("type") == "ec2" and not target.get("instance_id"):
        return {"status": "INVALID", "reason": "EC2 target needs an instance ID"}
    if target.get("account_id", os.environ.get("WORKLOAD_ACCOUNT_ID")) != os.environ.get("WORKLOAD_ACCOUNT_ID"):
        return {"status": "INVALID", "reason": "account outside configured workload"}
    if target.get("region", REGION) != REGION:
        return {"status": "INVALID", "reason": "region outside configured workload"}
    if target.get("type") == "ec2" and target.get("instance_id"):
        try:
            creds = boto3.client("sts", region_name=REGION).assume_role(
                RoleArn=f"arn:aws:iam::{os.environ['WORKLOAD_ACCOUNT_ID']}:role/{os.environ.get('PROJECT', 'ea')}-collection-target",
                RoleSessionName=f"ea-validate-{case_id[:20]}", DurationSeconds=900,
            )["Credentials"]
            ec2 = boto3.client("ec2", region_name=REGION,
                               aws_access_key_id=creds["AccessKeyId"],
                               aws_secret_access_key=creds["SecretAccessKey"],
                               aws_session_token=creds["SessionToken"])
            resp = ec2.describe_instances(InstanceIds=[target["instance_id"]])
            reservations = resp.get("Reservations", [])
            if not reservations:
                return {"status": "INVALID", "reason": "instance not found"}

            instance = reservations[0]["Instances"][0]
            tags = {t["Key"]: t["Value"] for t in instance.get("Tags", [])}
            if tags.get("EACollectable") != "true":
                return {"status": "INVALID", "reason": "instance not collectable"}
        except Exception as e:
            logger.warning("Instance check failed: %s", e)
            return {"status": "INVALID", "reason": "target could not be verified"}

    dedup_key = f"{trigger.get('space_id', 'default')}#{trigger['alert_id']}#{trigger.get('playbook_version', '1.0')}"

    ddb = boto3.resource("dynamodb", region_name=REGION)
    dedup_table = ddb.Table(DEDUP_TABLE)

    try:
        dedup_table.put_item(
            Item={
                "dedup_key": dedup_key,
                "case_id": case_id,
                "created_at": trigger.get("detected_at", ""),
                "ttl": int(time.time()) + 7 * 86400,
            },
            ConditionExpression="attribute_not_exists(dedup_key)",
        )
    except ddb.meta.client.exceptions.ConditionalCheckFailedException:
        logger.info("Duplicate alert: %s", dedup_key)
        return {"status": "DUPLICATE", "case_id": case_id}

    cases_table = ddb.Table(CASES_TABLE)
    cases_table.put_item(
        Item={
            "case_id": case_id,
            "status": "VALIDATED",
            "created_at": trigger.get("detected_at", ""),
            "updated_at": trigger.get("detected_at", ""),
            "trigger": trigger,
            "target": target,
            "jobs": [],
        }
    )

    logger.info("Case %s validated", case_id)
    return {"status": "VALID", "case_id": case_id}
