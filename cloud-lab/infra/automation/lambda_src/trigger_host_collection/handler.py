"""ea-trigger-host-collection: SSM SendCommand → Velociraptor 오프라인 수집 → 결과 확인."""

import logging
import os
import time
import hashlib
import json
import re
from botocore.config import Config

import boto3

logger = logging.getLogger("ea")
logger.setLevel(logging.INFO)

REGION = os.environ.get("REGION", "ap-northeast-2")
WORKLOAD_ACCOUNT_ID = os.environ.get("WORKLOAD_ACCOUNT_ID", "")
PROJECT = os.environ.get("PROJECT", "ea")
STAGING_BUCKET = os.environ.get("STAGING_BUCKET", "")


def lambda_handler(event, context):
    case_id = event["case_id"]
    instance_id = event["instance_id"]
    ssm_document = f"{PROJECT}-VelociraptorOfflineCollect"

    logger.info("Triggering host collection for %s on %s", case_id, instance_id)

    sts = boto3.client("sts", region_name=REGION)
    creds = sts.assume_role(
        RoleArn=f"arn:aws:iam::{WORKLOAD_ACCOUNT_ID}:role/{PROJECT}-collection-target",
        RoleSessionName=f"ea-host-{case_id[:20]}",
        DurationSeconds=900,
    )["Credentials"]

    ssm = boto3.client(
        "ssm",
        region_name=REGION,
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )

    s3 = boto3.client('s3', region_name=REGION, config=Config(signature_version='s3v4'))
    object_key = f'cases/{case_id}/host-triage/{instance_id}/triage.zip'
    upload_url = s3.generate_presigned_url('put_object', Params={
        'Bucket':STAGING_BUCKET,'Key':object_key,'ServerSideEncryption':'aws:kms',
        'SSEKMSKeyId':os.environ['EVIDENCE_KMS_KEY_ARN'],
        'Metadata':{'source-kind':'velociraptor-zip'}}, ExpiresIn=600)
    resp = ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName=ssm_document,
        Parameters={
            "CaseId": [case_id],
            "UploadUrl": [upload_url],
        },
        TimeoutSeconds=300,
        Comment=f"EA evidence collection for {case_id}",
    )

    command_id = resp["Command"]["CommandId"]
    logger.info("SSM command sent: %s", command_id)

    max_wait = 330
    waited = 0
    status = "InProgress"

    while waited < max_wait and status in {"Pending", "InProgress", "Delayed"}:
        time.sleep(10)
        waited += 10

        try:
            inv = ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id,
            )
            status = inv["Status"]
        except ssm.exceptions.InvocationDoesNotExist:
            continue

    if status != "Success":
        return {"status": "PARTIAL", "ssm_status": status, "command_id": command_id,
                "error": "Host collection did not finish successfully"}

    try:
        head = s3.head_object(Bucket=STAGING_BUCKET,Key=object_key)
        if head.get('ContentLength',0) <= 0 or head.get('VersionId') in (None,'','null'):
            raise ValueError('Host upload has no immutable non-empty object')
    except Exception:
        return {'status':'PARTIAL','command_id':command_id,'error':'SSM succeeded but evidence upload is absent'}
    try:
        report=json.loads(inv.get('StandardOutputContent','').strip().splitlines()[-1])
        if not re.fullmatch('[a-f0-9]{64}',report.get('sha256','')) or report['size_bytes']!=head['ContentLength']:
            raise ValueError('Invalid collector report')
    except (ValueError,KeyError,IndexError):
        return {'status':'PARTIAL','command_id':command_id,'error':'Collector digest report is missing or invalid'}
    output_key = object_key

    return {
        "command_id": command_id,
        "status": report.get("status", "PARTIAL"),
        "producer_sha256": report["sha256"],
        "version_id": head["VersionId"],
        "warnings": report.get("warnings", []),
        "output_key": output_key,
    }
