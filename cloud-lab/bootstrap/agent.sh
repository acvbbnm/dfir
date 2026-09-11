#!/bin/bash
set -euo pipefail
umask 077
: "${FLEET_URL:?A real Fleet HTTPS URL is required}"
: "${FLEET_CA_FILE:?Fleet CA certificate file is required}"
: "${ENROLLMENT_TOKEN:?Enrollment token is required}"
: "${AGENT_VERSION:?An exact compatible Elastic Agent version is required}"
: "${AGENT_SHA256:?Verified Agent archive SHA-256 is required}"
[[ "$FLEET_URL" == https://* ]]
[[ "$AGENT_VERSION" =~ ^8\.[0-9]+\.[0-9]+$ ]]
[[ "$AGENT_SHA256" =~ ^[a-f0-9]{64}$ ]]
[ -r "$FLEET_CA_FILE" ]
if command -v elastic-agent >/dev/null; then elastic-agent status; exit 0; fi
work=$(mktemp -d /var/tmp/ea-agent.XXXXXX)
trap 'rm -rf -- "$work"' EXIT
curl --fail --silent --show-error --location --proto '=https' \
  "https://artifacts.elastic.co/downloads/beats/elastic-agent/elastic-agent-${AGENT_VERSION}-linux-x86_64.tar.gz" -o "$work/agent.tar.gz"
printf '%s  %s\n' "$AGENT_SHA256" "$work/agent.tar.gz" | sha256sum --check --status
tar -xzf "$work/agent.tar.gz" --no-same-owner -C "$work"
"$work/elastic-agent-${AGENT_VERSION}-linux-x86_64/elastic-agent" install \
  --url="$FLEET_URL" --enrollment-token="$ENROLLMENT_TOKEN" \
  --certificate-authorities="$FLEET_CA_FILE" --non-interactive
elastic-agent status
