#!/bin/bash
set -euo pipefail
umask 077
: "${FLEET_URL:?A real Fleet HTTPS URL is required}"
: "${FLEET_CA_FILE:?Fleet CA certificate file is required}"
: "${EA_AGENT_ROLE:=endpoint}"
if [ "$EA_AGENT_ROLE" = endpoint ]; then : "${ENROLLMENT_TOKEN:?Enrollment token is required}"; fi
: "${AGENT_VERSION:?An exact compatible Elastic Agent version is required}"
: "${AGENT_SHA512:?Official Agent archive SHA-512 is required}"
[[ "$FLEET_URL" == https://* ]]
[[ "$AGENT_VERSION" =~ ^8\.[0-9]+\.[0-9]+$ ]]
[[ "$AGENT_SHA512" =~ ^[a-f0-9]{128}$ ]]
[ -r "$FLEET_CA_FILE" ]
if command -v elastic-agent >/dev/null; then elastic-agent status; exit 0; fi
work=$(mktemp -d /var/tmp/ea-agent.XXXXXX)
trap 'rm -rf -- "$work"' EXIT
curl --fail --silent --show-error --location --proto '=https' \
  "https://artifacts.elastic.co/downloads/beats/elastic-agent/elastic-agent-${AGENT_VERSION}-linux-x86_64.tar.gz" -o "$work/agent.tar.gz"
printf '%s  %s\n' "$AGENT_SHA512" "$work/agent.tar.gz" | sha512sum --check --status
tar -xzf "$work/agent.tar.gz" --no-same-owner -C "$work"
agent="$work/elastic-agent-${AGENT_VERSION}-linux-x86_64/elastic-agent"
if [ "$EA_AGENT_ROLE" = fleet ]; then
  : "${FLEET_SERVER_SERVICE_TOKEN:?Service token required}"
  : "${FLEET_SERVER_ES:?HTTPS Elasticsearch URL required}"
  : "${FLEET_SERVER_CERT:?Fleet TLS certificate required}"
  : "${FLEET_SERVER_KEY:?Fleet TLS private key required}"
  "$agent" install --url="$FLEET_URL" --fleet-server-es="$FLEET_SERVER_ES" \
    --fleet-server-service-token="$FLEET_SERVER_SERVICE_TOKEN" --fleet-server-policy=ea-fleet-v1 \
    --fleet-server-es-ca="$FLEET_CA_FILE" --certificate-authorities="$FLEET_CA_FILE" \
    --fleet-server-cert="$FLEET_SERVER_CERT" --fleet-server-cert-key="$FLEET_SERVER_KEY" --non-interactive
elif [ "$EA_AGENT_ROLE" = endpoint ]; then
  "$agent" install --url="$FLEET_URL" --enrollment-token="$ENROLLMENT_TOKEN" \
    --certificate-authorities="$FLEET_CA_FILE" --non-interactive
else
  echo 'EA_AGENT_ROLE must be endpoint or fleet' >&2; exit 2
fi
elastic-agent status
