"""metadata observer — EC2/SG/IAM 주기적 상태 조회 → S3 저장."""

import json
import logging
import os
import time
from datetime import datetime, timezone

import boto3

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ea-metadata-observer")

REGION = os.environ.get("REGION", "ap-northeast-2")
STAGING_BUCKET = os.environ.get("STAGING_BUCKET", "")
OBSERVE_INTERVAL = int(os.environ.get("OBSERVE_INTERVAL", "300"))
TARGET_TAG_KEY = "EACollectable"
TARGET_TAG_VALUE = "true"


def observe_instances(ec2) -> list:
    resp = ec2.describe_instances(
        Filters=[{"Name": f"tag:{TARGET_TAG_KEY}", "Values": [TARGET_TAG_VALUE]}]
    )
    instances = []
    for r in resp.get("Reservations", []):
        for i in r["Instances"]:
            instances.append({
                "instance_id": i["InstanceId"],
                "state": i["State"]["Name"],
                "instance_type": i["InstanceType"],
                "private_ip": i.get("PrivateIpAddress"),
                "security_groups": [sg["GroupId"] for sg in i.get("SecurityGroups", [])],
                "iam_profile": i.get("IamInstanceProfile", {}).get("Arn"),
                "tags": {t["Key"]: t["Value"] for t in i.get("Tags", [])},
            })
    return instances


def observe_security_groups(ec2, sg_ids: list) -> list:
    if not sg_ids:
        return []
    resp = ec2.describe_security_groups(GroupIds=list(set(sg_ids)))
    return [
        {
            "group_id": sg["GroupId"],
            "group_name": sg["GroupName"],
            "ingress_rules": len(sg.get("IpPermissions", [])),
            "egress_rules": len(sg.get("IpPermissionsEgress", [])),
        }
        for sg in resp["SecurityGroups"]
    ]


def save_snapshot(s3, snapshot: dict):
    now = datetime.now(timezone.utc)
    key = f"metadata-snapshots/{now.strftime('%Y-%m-%d')}/{now.strftime('%H%M%S')}.json"

    s3.put_object(
        Bucket=STAGING_BUCKET,
        Key=key,
        Body=json.dumps(snapshot, ensure_ascii=False, default=str).encode("utf-8"),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
    )
    logger.info("Saved snapshot to %s", key)


def run_once():
    ec2 = boto3.client("ec2", region_name=REGION)
    s3 = boto3.client("s3", region_name=REGION)

    instances = observe_instances(ec2)
    all_sg_ids = []
    for inst in instances:
        all_sg_ids.extend(inst["security_groups"])

    sgs = observe_security_groups(ec2, all_sg_ids)

    snapshot = {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "instances": instances,
        "security_groups": sgs,
    }

    save_snapshot(s3, snapshot)


def main():
    logger.info("Metadata observer started (interval=%ds)", OBSERVE_INTERVAL)
    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            break
        except Exception:
            logger.exception("Observation cycle error")
        time.sleep(OBSERVE_INTERVAL)


if __name__ == "__main__":
    main()
