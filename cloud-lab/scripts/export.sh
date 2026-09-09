#!/usr/bin/env bash
set -euo pipefail

# EA Cloud Lab — 증거/결과 내보내기
# 사용법: ./scripts/export.sh <case_id> [output_dir]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CASE_ID="${1:?사용법: export.sh <case_id> [output_dir]}"
OUTPUT_DIR="${2:-$PROJECT_DIR/results/$CASE_ID}"

echo "=== EA Evidence Export: $CASE_ID ==="

mkdir -p "$OUTPUT_DIR"/{evidence,metadata,timeline,manifests}

EVIDENCE_BUCKET="ea-evidence-final"
STAGING_BUCKET="ea-evidence-staging"

echo "[1/5] DynamoDB 케이스 레코드 조회"
aws dynamodb get-item \
    --table-name ea-cases \
    --key "{\"case_id\": {\"S\": \"$CASE_ID\"}}" \
    --output json > "$OUTPUT_DIR/metadata/case_record.json"

echo "[2/5] S3 최종 증거 다운로드"
aws s3 sync "s3://$EVIDENCE_BUCKET/$CASE_ID/" "$OUTPUT_DIR/evidence/" --quiet

echo "[3/5] S3 스테이징 메타데이터 다운로드"
aws s3 sync "s3://$STAGING_BUCKET/$CASE_ID/" "$OUTPUT_DIR/metadata/staging/" --quiet

echo "[4/5] 매니페스트 검증"
MANIFEST="$OUTPUT_DIR/evidence/manifest.json"
if [ -f "$MANIFEST" ]; then
    echo "  매니페스트 발견 — SHA-256 검증 시작"
    python3 -c "
import json, hashlib, sys
from pathlib import Path

manifest = json.loads(Path('$MANIFEST').read_text())
errors = []
for item in manifest.get('items', []):
    fpath = Path('$OUTPUT_DIR/evidence') / item['key'].split('/')[-1]
    if not fpath.exists():
        errors.append(f'누락: {item[\"key\"]}')
        continue
    actual = hashlib.sha256(fpath.read_bytes()).hexdigest()
    if actual != item.get('sha256', ''):
        errors.append(f'불일치: {item[\"key\"]} expected={item[\"sha256\"][:16]}... actual={actual[:16]}...')
if errors:
    print('검증 실패:')
    for e in errors: print(f'  - {e}')
    sys.exit(1)
print(f'검증 성공: {len(manifest.get(\"items\", []))}개 항목 일치')
"
else
    echo "  매니페스트 없음 — 검증 스킵"
fi

echo "[5/5] 내보내기 완료"
echo "  출력 경로: $OUTPUT_DIR"
echo "  케이스:    $CASE_ID"
ls -la "$OUTPUT_DIR/"
