#!/bin/bash
set -euo pipefail

# Velociraptor offline collector 설치 — /opt/ea-tools/
# 실행 시 환경변수 필요: VELO_VERSION, VELO_SHA256

VELO_VERSION="${VELO_VERSION:-0.73.3}"
VELO_SHA256="${VELO_SHA256:-TODO_VERIFY_ON_DOWNLOAD}"
INSTALL_DIR="/opt/ea-tools"

mkdir -p "$INSTALL_DIR"

DOWNLOAD_URL="https://github.com/Velocidex/velociraptor/releases/download/v${VELO_VERSION}/velociraptor-v${VELO_VERSION}-linux-amd64"

curl -sL -o "${INSTALL_DIR}/velociraptor-collector" "$DOWNLOAD_URL"

ACTUAL_SHA=$(sha256sum "${INSTALL_DIR}/velociraptor-collector" | cut -d' ' -f1)

if [ "$VELO_SHA256" != "TODO_VERIFY_ON_DOWNLOAD" ] && [ "$ACTUAL_SHA" != "$VELO_SHA256" ]; then
  echo "ERROR: SHA-256 mismatch! Expected: $VELO_SHA256, Got: $ACTUAL_SHA"
  rm -f "${INSTALL_DIR}/velociraptor-collector"
  exit 1
fi

echo "SHA-256: $ACTUAL_SHA" > "${INSTALL_DIR}/velociraptor-collector.sha256"
chmod 755 "${INSTALL_DIR}/velociraptor-collector"

echo "EA Velociraptor setup complete (v${VELO_VERSION})"
