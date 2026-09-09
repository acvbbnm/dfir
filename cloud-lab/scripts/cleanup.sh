#!/usr/bin/env bash
set -euo pipefail

# EA Cloud Lab — 전체 인프라 제거 (Phase E 최종 정리)
# 사용법: ./scripts/cleanup.sh [--confirm]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== EA Cloud Lab 전체 제거 ==="
echo "경고: 이 작업은 모든 AWS 리소스를 삭제합니다."
echo ""

if [ "${1:-}" != "--confirm" ]; then
    echo "실행하려면: ./scripts/cleanup.sh --confirm"
    echo ""
    echo "제거 순서:"
    echo "  1. Automation (Lambda, StepFunctions, EventBridge, DynamoDB)"
    echo "  2. Lab (EC2, RDS, ALB, WAF, VPC)"
    echo "  3. Foundation (S3, KMS, CloudTrail, Budget)"
    echo ""
    echo "주의사항:"
    echo "  - S3 버킷은 비어있어야 삭제 가능 (증거 보존 필요 시 먼저 export.sh 실행)"
    echo "  - KMS 키는 삭제 대기 (7일) 후 영구 삭제"
    echo "  - DynamoDB 테이블 데이터는 즉시 삭제됨"
    exit 0
fi

echo "[1/4] 결과 디렉토리 백업 확인"
if [ -d "$PROJECT_DIR/results" ] && [ "$(ls -A "$PROJECT_DIR/results" 2>/dev/null)" ]; then
    echo "  results/ 에 기존 데이터 있음 — 이미 백업됨으로 간주"
else
    echo "  results/ 비어있음 — 증거 내보내기가 필요하면 Ctrl+C로 중단"
    sleep 5
fi

echo "[2/4] Automation 모듈 제거"
cd "$PROJECT_DIR/infra/automation"
if [ -f "terraform.tfstate" ] || [ -d ".terraform" ]; then
    tofu destroy -auto-approve
else
    echo "  Automation 상태 없음 — 스킵"
fi

echo "[3/4] Lab 모듈 제거"
cd "$PROJECT_DIR/infra/lab"
if [ -f "terraform.tfstate" ] || [ -d ".terraform" ]; then
    tofu destroy -var="operation_mode=idle" -auto-approve
else
    echo "  Lab 상태 없음 — 스킵"
fi

echo "[4/4] Foundation 모듈 제거"
cd "$PROJECT_DIR/infra/foundation"
if [ -f "terraform.tfstate" ] || [ -d ".terraform" ]; then
    echo "  S3 버킷 비우기 (versioned objects 포함)"
    for bucket in ea-evidence-staging ea-evidence-final ea-logs-waf ea-logs-alb ea-logs-flow; do
        aws s3 rm "s3://$bucket" --recursive 2>/dev/null || true
        aws s3api list-object-versions --bucket "$bucket" --output json 2>/dev/null | \
            python3 -c "
import json, sys
data = json.load(sys.stdin)
for key in ['Versions', 'DeleteMarkers']:
    for obj in data.get(key, []):
        print(f'{obj[\"Key\"]} {obj[\"VersionId\"]}')
" 2>/dev/null | while read -r key vid; do
            aws s3api delete-object --bucket "$bucket" --key "$key" --version-id "$vid" 2>/dev/null || true
        done
    done
    tofu destroy -auto-approve
else
    echo "  Foundation 상태 없음 — 스킵"
fi

echo ""
echo "=== 정리 완료 ==="
echo "남은 수동 확인 사항:"
echo "  - AWS Console에서 잔여 리소스 확인"
echo "  - KMS 키 삭제 대기 상태 확인 (7일 후 영구 삭제)"
echo "  - CloudWatch 로그 그룹 수동 삭제 (보존 필요 시 유지)"
