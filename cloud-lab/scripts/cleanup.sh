#!/usr/bin/env bash
set -euo pipefail
# Produce a reviewable destroy plan for one exact state. Evidence foundation is retained.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
: "${EA_STAGE:?Choose automation or lab; run automation first}"
case "$EA_STAGE" in automation|lab) ;; *) echo 'Foundation deletion is not part of the session shutdown' >&2; exit 1;; esac
: "${EA_TFVARS:?Private tfvars path required}"
: "${EA_BACKEND_CONFIG:?Private backend configuration required}"
: "${EA_EXPORT_DIR:?Verified exported case directory required}"
python3 "$SCRIPT_DIR/evidence_bundle.py" verify "$EA_EXPORT_DIR"
cd "$PROJECT_DIR/infra/$EA_STAGE"
tofu init -input=false -lockfile=readonly -backend-config="$EA_BACKEND_CONFIG"
tofu plan -destroy -input=false -var-file="$EA_TFVARS" -out=session-destroy.tfplan
echo 'Review this exact plan, then run tofu apply session-destroy.tfplan in this directory.'
echo 'S3 evidence, state, audit history and KMS keys are retained. Inventory residual resources afterward.'
