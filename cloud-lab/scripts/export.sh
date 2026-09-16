#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
: "${EA_FINAL_BUCKET:?Actual final evidence bucket is required}"
: "${EA_SECURITY_PROFILE:?Named AWS profile is required}"
exec python3 "$SCRIPT_DIR/evidence_bundle.py" download "${1:?Case ID required}" \
  "${2:?Destination outside the source repository required}" \
  --bucket "$EA_FINAL_BUCKET" --profile "$EA_SECURITY_PROFILE" --region "${AWS_REGION:-ap-northeast-2}"
