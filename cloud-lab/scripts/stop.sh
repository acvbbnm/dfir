#!/usr/bin/env bash
set -euo pipefail

# EA Cloud Lab — idle 모드 전환 (비용 절감)
# 사용법: ./scripts/stop.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== EA Cloud Lab → idle 모드 전환 ==="

cd "$PROJECT_DIR/infra/lab"
echo "[1/3] Lab → idle 모드 (NAT/Endpoints 제거)"
tofu plan -var="operation_mode=idle" -out=tfplan
echo "Plan 완료. 적용하려면: tofu apply tfplan"

echo "[2/3] EC2 인스턴스 중지 (수동)"
echo "  aws ec2 stop-instances --instance-ids \$(tofu output -json instance_ids | jq -r '.[]')"

echo "[3/3] 완료."
echo ""
echo "idle 모드에서는:"
echo "  - NAT Gateway 삭제 → 시간당 과금 중단"
echo "  - SSM VPC Endpoints 삭제 → 시간당 과금 중단"
echo "  - EC2 인스턴스 수동 중지 권장 (EBS만 과금)"
echo "  - S3/DynamoDB/KMS는 유지 (미사용 시 거의 무료)"
echo ""
echo "재시작: ./scripts/start.sh operate"
