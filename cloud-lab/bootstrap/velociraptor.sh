#!/bin/bash
set -euo pipefail
# Install a generated offline collector, not a renamed generic Velociraptor binary.
# Build/sign the selected profile first; retain its version and configuration manifest.
: "${COLLECTOR_URL:?URL of the generated offline collector is required}"
: "${COLLECTOR_SHA256:?Verified generated collector SHA-256 is required}"
[[ "$COLLECTOR_URL" == https://* ]]
[[ "$COLLECTOR_SHA256" =~ ^[a-f0-9]{64}$ ]]
install -d -m 0755 /opt/ea-tools
artifact=$(mktemp /opt/ea-tools/.collector.XXXXXX)
trap 'rm -f -- "$artifact"' EXIT
curl --fail --silent --show-error --location --proto '=https' "$COLLECTOR_URL" -o "$artifact"
printf '%s  %s\n' "$COLLECTOR_SHA256" "$artifact" | sha256sum --check --status
install -m 0755 "$artifact" /opt/ea-tools/velociraptor-collector
printf '%s  velociraptor-collector\n' "$COLLECTOR_SHA256" > /opt/ea-tools/velociraptor-collector.sha256
echo 'Collector installed; its CLI/profile must be validated against the SSM document before use'
