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

    # Canonical contract: the collector hashes space/alert/playbook into a stable case ID; every downstream stage
    # (SSM document, verify-finalize, collectors, export) enforces ^CASE-[A-Za-z0-9_-]{1,59}$.
    # A looser pattern here would reserve a case that the rest of the pipeline later rejects.
    if not re.fullmatch(r"CASE-[A-Za-z0-9_-]{1,59}", case_id):
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

    # Both records commit together. A reserved dedup key can no longer orphan a case.
    from boto3.dynamodb.types import TypeSerializer
    from botocore.exceptions import ClientError
    serialize = TypeSerializer().serialize
    owner = event.get('execution_id', case_id)
    ddb = boto3.client('dynamodb', region_name=REGION)
    stamp = trigger.get('detected_at', '')
    entries = [
        (DEDUP_TABLE, 'dedup_key', {'dedup_key':dedup_key,'case_id':case_id,
         'execution_id':owner,'created_at':stamp,'ttl':int(time.time())+7*86400}),
        (CASES_TABLE, 'case_id', {'case_id':case_id,'execution_id':owner,'status':'VALIDATED',
         'created_at':stamp,'updated_at':stamp,'trigger':trigger,'target':target,'jobs':[]})]
    try:
        ddb.transact_write_items(TransactItems=[{'Put':{'TableName':table,
            'Item':{k:serialize(v) for k,v in item.items()},
            'ConditionExpression':'attribute_not_exists('+key+')'}} for table,key,item in entries])
    except ClientError as exc:
        if exc.response['Error']['Code']!='TransactionCanceledException':raise
        reasons=exc.response.get('CancellationReasons',[])
        if not any(r.get('Code')=='ConditionalCheckFailed' for r in reasons):raise
        existing=ddb.get_item(TableName=CASES_TABLE,Key={'case_id':{'S':case_id}},ConsistentRead=True).get('Item',{})
        if existing.get('execution_id',{}).get('S')==owner and existing.get('status',{}).get('S')=='VALIDATED':
            return {'status':'VALID','case_id':case_id}
        return {'status':'DUPLICATE','case_id':case_id}

    logger.info("Case %s validated", case_id)
    return {"status": "VALID", "case_id": case_id}
