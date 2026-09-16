#!/usr/bin/env bash
set -euo pipefail
# Prepare the exact idle infrastructure plan; compute/database stopping is a separate explicit action.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export EA_STAGE=lab
bash "$SCRIPT_DIR/start.sh" idle
echo 'idle removes NAT/API endpoints only. EC2, RDS, ALB, EBS, snapshots, S3 and KMS can still accrue charges.'
echo 'Before applying: disable new collection, finish/export active cases, then stop compute using session_control.py.'
echo 'RDS can restart automatically after its maximum stopped period; inspect daily and destroy the lab after the session.'
