#!/bin/bash
set -euo pipefail
umask 077
BOOTSTRAP_DIR="${EA_BOOTSTRAP_DIR:-/opt/ea-bootstrap}"
source "$BOOTSTRAP_DIR/environment.sh"
: "${COLLECTOR_URL:?Exact standalone Velociraptor release URL required}"
: "${COLLECTOR_SHA256:?Verified SHA-256 required}"
: "${EVIDENCE_BUCKET:?Evidence bucket required}"
: "${EVIDENCE_KMS_KEY_ARN:?Evidence KMS key ARN required}"
[[ "$COLLECTOR_URL" == https://github.com/Velocidex/velociraptor/releases/download/* ]]
[[ "$COLLECTOR_SHA256" =~ ^[a-f0-9]{64}$ ]]
install -d -m 0755 /opt/ea-tools /opt/ea-tools/artifacts
artifact=$(mktemp /opt/ea-tools/.velociraptor.XXXXXX)
trap 'rm -f -- "$artifact"' EXIT
curl --fail --silent --show-error --location --proto '=https' "$COLLECTOR_URL" -o "$artifact"
printf '%s  %s\n' "$COLLECTOR_SHA256" "$artifact" | sha256sum --check --status
install -m 0755 "$artifact" /opt/ea-tools/velociraptor
install -m 0644 "$BOOTSTRAP_DIR/collectors/linux-triage.yaml" /opt/ea-tools/artifacts/linux-triage.yaml
install -m 0700 "$BOOTSTRAP_DIR/collectors/host_collect.py" /opt/ea-tools/host_collect.py
python3 - <<'PY'
import json,os,pathlib
pathlib.Path('/opt/ea-tools/collector-config.json').write_text(json.dumps({
 'sha256':os.environ['COLLECTOR_SHA256'],'bucket':os.environ['EVIDENCE_BUCKET'],
 'region':os.environ['AWS_REGION'],'kms_key':os.environ['EVIDENCE_KMS_KEY_ARN']}))
PY
/opt/ea-tools/velociraptor version
