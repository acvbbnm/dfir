#!/bin/bash
set -euo pipefail
umask 077
BOOTSTRAP_DIR="${EA_BOOTSTRAP_DIR:-/opt/ea-bootstrap}"
source "$BOOTSTRAP_DIR/environment.sh"
id ea-collector >/dev/null 2>&1 || useradd --system --home /var/lib/ea-collector --shell /usr/sbin/nologin ea-collector
install -d -m 0750 -o root -g ea-collector /etc/ea-collector /opt/ea-collectors
install -d -m 0700 -o ea-collector -g ea-collector /var/lib/ea-collector
install -m 0640 -o root -g ea-collector /etc/elasticsearch/ea-certs/ca/ca.crt /etc/ea-collector/es-ca.pem
python3 "$BOOTSTRAP_DIR/configure_collectors.py"
chown root:ea-collector /etc/ea-collector/env /etc/ea-collector/cloud-sources.json
for name in alert_collector cloud_logs; do
  install -m 0644 "$BOOTSTRAP_DIR/collectors/$name.py" /opt/ea-collectors/
  install -m 0644 "$BOOTSTRAP_DIR/collectors/$name.service" "/etc/systemd/system/ea-$name.service"
done
systemctl daemon-reload
systemctl enable --now ea-alert_collector ea-cloud_logs
