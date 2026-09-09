"""ea-trigger-host-collection: SSM SendCommand → Velociraptor 오프라인 수집 → 결과 확인."""

import logging
import os
import time

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
    ssm_document = event.get("ssm_document", f"{PROJECT}-VelociraptorOfflineCollect")

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

    resp = ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName=ssm_document,
        Parameters={
            "CaseId": [case_id],
            "StagingBucket": [STAGING_BUCKET],
            "CollectionProfile": ["standard"],
        },
        TimeoutSeconds=300,
        Comment=f"EA evidence collection for {case_id}",
    )

    command_id = resp["Command"]["CommandId"]
    logger.info("SSM command sent: %s", command_id)

    max_wait = 280
    waited = 0
    status = "InProgress"

    while waited < max_wait and status == "InProgress":
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

    output_key = f"cases/{case_id}/host-triage/"

    return {
        "command_id": command_id,
        "status": status,
        "output_key": output_key,
    }
