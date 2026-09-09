#!/usr/bin/env bash
set -euo pipefail

# EA Cloud Lab — 인프라 시작 (setup → operate 전환)
# 사용법: ./scripts/start.sh [setup|operate]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
MODE="${1:-setup}"

echo "=== EA Cloud Lab Start (mode: $MODE) ==="

cd "$PROJECT_DIR/infra/foundation"
echo "[1/4] Foundation — tofu init + plan"
tofu init -upgrade
tofu plan -out=tfplan
echo "Foundation plan 완료. 'tofu apply tfplan'으로 적용하세요."

cd "$PROJECT_DIR/infra/lab"
echo "[2/4] Lab — tofu init + plan (mode=$MODE)"
tofu init -upgrade
tofu plan -var="operation_mode=$MODE" -out=tfplan
echo "Lab plan 완료. 'tofu apply tfplan'으로 적용하세요."

if [ "$MODE" = "operate" ]; then
    cd "$PROJECT_DIR/infra/automation"
    echo "[3/4] Automation — tofu init + plan"
    tofu init -upgrade
    tofu plan -out=tfplan
    echo "Automation plan 완료. 'tofu apply tfplan'으로 적용하세요."
else
    echo "[3/4] Automation — setup 모드에서는 스킵"
fi

echo "[4/4] 완료."
echo ""
echo "다음 단계:"
echo "  1. 각 모듈 디렉토리에서 'tofu apply tfplan'"
echo "  2. setup 모드 후 operate로 전환:"
echo "     ./scripts/start.sh operate"
echo "  3. 인스턴스 부트스트랩 확인:"
echo "     aws ssm describe-instance-information"
