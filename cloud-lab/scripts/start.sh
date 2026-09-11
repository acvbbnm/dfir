#!/usr/bin/env bash
set -euo pipefail
# Usage preserved: start.sh [setup|operate|idle]
# Select one dependency stage: EA_STAGE=foundation|lab|automation.
# EA_TFVARS points to the private input file; EA_BACKEND_CONFIG supplies the S3 backend.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
MODE="${1:-setup}"
: "${EA_STAGE:?Choose foundation, lab or automation}"
: "${EA_TFVARS:?Provide the private tfvars file path}"
[[ "$MODE" =~ ^(setup|operate|idle)$ ]] || { echo 'Invalid mode' >&2; exit 2; }
[[ "$EA_STAGE" =~ ^(foundation|lab|automation)$ ]] || { echo 'Invalid stage' >&2; exit 2; }
[ -f "$EA_TFVARS" ] || { echo 'tfvars file is missing' >&2; exit 2; }
TFVARS=$(realpath "$EA_TFVARS")
init_args=(-input=false -lockfile=readonly)
if [ -n "${EA_BACKEND_CONFIG:-}" ]; then
  init_args+=("-backend-config=$(realpath "$EA_BACKEND_CONFIG")")
elif [ "$EA_STAGE" != foundation ]; then
  echo 'EA_BACKEND_CONFIG is required after foundation creates the state bucket' >&2
  exit 2
fi
cd "$PROJECT_DIR/infra/$EA_STAGE"
tofu init "${init_args[@]}"
tofu validate
plan_args=(-input=false "-var-file=$TFVARS" -out=tfplan)
if [ "$EA_STAGE" = lab ]; then plan_args+=("-var=operation_mode=$MODE"); fi
tofu plan "${plan_args[@]}"
echo "Plan saved for $EA_STAGE. No resources applied. Review the plan before applying it."
