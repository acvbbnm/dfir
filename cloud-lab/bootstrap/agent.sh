#!/bin/bash
set -euo pipefail

# Elastic Agent 설치 + Fleet 등록
# 실행 시 환경변수 필요: FLEET_URL, ENROLLMENT_TOKEN

FLEET_URL="${FLEET_URL:-https://SOC_PRIVATE_IP:8220}"
ENROLLMENT_TOKEN="${ENROLLMENT_TOKEN:-TODO_SET_AT_DEPLOY}"
AGENT_VERSION="${AGENT_VERSION:-8.17.0}"

cd /tmp
curl -sL -O "https://artifacts.elastic.co/downloads/beats/elastic-agent/elastic-agent-${AGENT_VERSION}-linux-x86_64.tar.gz"
tar xzf "elastic-agent-${AGENT_VERSION}-linux-x86_64.tar.gz"
cd "elastic-agent-${AGENT_VERSION}-linux-x86_64"

./elastic-agent install \
  --url="${FLEET_URL}" \
  --enrollment-token="${ENROLLMENT_TOKEN}" \
  --insecure \
  --non-interactive

cd /tmp
rm -rf "elastic-agent-${AGENT_VERSION}-linux-x86_64"*

echo "EA Agent setup complete"
