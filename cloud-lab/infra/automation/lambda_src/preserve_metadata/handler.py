"""ea-preserve-metadata: Workload AssumeRole → 대상 리소스 상태 조회 → S3 저장."""

import json
import logging
import os
from datetime import datetime, timezone

import boto3

logger = logging.getLogger("ea")
logger.setLevel(logging.INFO)

REGION = os.environ.get("REGION", "ap-northeast-2")
WORKLOAD_ACCOUNT_ID = os.environ.get("WORKLOAD_ACCOUNT_ID", "")
PROJECT = os.environ.get("PROJECT", "ea")
STAGING_BUCKET = os.environ.get("STAGING_BUCKET", "")


def lambda_handler(event, context):
    case_id = event["case_id"]
    target = event["target"]

    logger.info("Preserving metadata for case %s", case_id)

    sts = boto3.client("sts", region_name=REGION)
    creds = sts.assume_role(
        RoleArn=f"arn:aws:iam::{WORKLOAD_ACCOUNT_ID}:role/{PROJECT}-collection-target",
        RoleSessionName=f"ea-metadata-{case_id[:20]}",
        DurationSeconds=900,
    )["Credentials"]

    session = boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=REGION,
    )

    preserved = []
    errors = []

    if target.get("instance_id"):
        try:
            ec2 = session.client("ec2")
            resp = ec2.describe_instances(InstanceIds=[target["instance_id"]])
            preserved.append({"type": "ec2_instance", "data": resp["Reservations"]})

            instance = resp["Reservations"][0]["Instances"][0]
            sg_ids = [sg["GroupId"] for sg in instance.get("SecurityGroups", [])]
            if sg_ids:
                sg_resp = ec2.describe_security_groups(GroupIds=sg_ids)
                preserved.append({"type": "security_groups", "data": sg_resp["SecurityGroups"]})

            eni_ids = [eni["NetworkInterfaceId"] for eni in instance.get("NetworkInterfaces", [])]
            if eni_ids:
                eni_resp = ec2.describe_network_interfaces(NetworkInterfaceIds=eni_ids)
                preserved.append({"type": "network_interfaces", "data": eni_resp["NetworkInterfaces"]})

            profile_arn = instance.get("IamInstanceProfile", {}).get("Arn", "")
            if profile_arn:
                iam = session.client("iam")
                profile_name = profile_arn.split("/")[-1]
                ip_resp = iam.get_instance_profile(InstanceProfileName=profile_name)
                preserved.append({"type": "instance_profile", "data": ip_resp["InstanceProfile"]})
        except Exception as e:
            errors.append({"source": "ec2", "error": str(e)})
            logger.warning("EC2 metadata error: %s", e)

    if target.get("rds_id"):
        try:
            rds = session.client("rds")
            resp = rds.describe_db_instances(DBInstanceIdentifier=target["rds_id"])
            preserved.append({"type": "rds_instance", "data": resp["DBInstances"]})
        except Exception as e:
            errors.append({"source": "rds", "error": str(e)})
            logger.warning("RDS metadata error: %s", e)

    result = {
        "case_id": case_id,
        "preserved_at": datetime.now(timezone.utc).isoformat(),
        "items": preserved,
        "errors": errors,
    }

    s3 = boto3.client("s3", region_name=REGION)
    s3.put_object(
        Bucket=STAGING_BUCKET,
        Key=f"cases/{case_id}/metadata/pre-response.json",
        Body=json.dumps(result, ensure_ascii=False, default=str).encode("utf-8"),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
    )

    logger.info("Preserved %d items, %d errors", len(preserved), len(errors))
    return {"preserved": [p["type"] for p in preserved], "errors": errors}
