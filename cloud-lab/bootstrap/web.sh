#!/bin/bash
set -euo pipefail
BOOTSTRAP_DIR="${EA_BOOTSTRAP_DIR:-/opt/ea-bootstrap}"
# shellcheck source=/dev/null
source "$BOOTSTRAP_DIR/environment.sh"
: "${APP_PRIVATE_IP:?APP_PRIVATE_IP is required}"
: "${ALB_SUBNET_CIDRS:?ALB_SUBNET_CIDRS is required}"
/bin/bash "$BOOTSTRAP_DIR/base.sh"
export DEBIAN_FRONTEND=noninteractive
# Ubuntu 24.04 repositories; installed versions are recorded after installation.
apt-get install -y nginx libnginx-mod-http-modsecurity modsecurity-crs suricata iptables-persistent
install -d -m 0750 -o www-data -g adm /var/log/modsecurity
install -m 0644 "$BOOTSTRAP_DIR/application/modsecurity/ea.conf" /etc/modsecurity/ea.conf
case "${WAF_MODE:-DetectionOnly}" in DetectionOnly|On) ;; *) echo 'Invalid WAF_MODE' >&2; exit 1;; esac
sed -i "s/^SecRuleEngine .*/SecRuleEngine ${WAF_MODE:-DetectionOnly}/" /etc/modsecurity/ea.conf
cat > /etc/logrotate.d/ea-modsecurity <<'ROTATE'
/var/log/modsecurity/*.json /var/log/nginx/access.json {
    daily
    rotate 7
    maxsize 20M
    missingok
    notifempty
    compress
    delaycompress
    create 0640 www-data adm
    sharedscripts
    postrotate
        /usr/sbin/nginx -s reopen
    endscript
}
ROTATE
install -d /etc/suricata/rules /etc/systemd/system/suricata.service.d
install -m 0644 "$BOOTSTRAP_DIR/application/suricata/local.rules" /etc/suricata/rules/local.rules
install -m 0644 "$BOOTSTRAP_DIR/application/suricata/suricata-ea.yaml" /etc/suricata/suricata-ea.yaml
python3 - "$BOOTSTRAP_DIR/application/nginx/default.conf" <<'PY'
import ipaddress, os, pathlib, sys
app = str(ipaddress.IPv4Address(os.environ['APP_PRIVATE_IP']))
cidrs = [str(ipaddress.IPv4Network(c)) for c in os.environ['ALB_SUBNET_CIDRS'].split(',')]
text = pathlib.Path(sys.argv[1]).read_text().replace('APP_PRIVATE_IP', app)
text = text.replace('ALB_TRUST_DIRECTIVES', '\n    '.join('set_real_ip_from ' + c + ';' for c in cidrs))
pathlib.Path('/etc/nginx/sites-available/default').write_text(text)
PY
nginx -t
suricata -T -c /etc/suricata/suricata-ea.yaml
cat > /etc/systemd/system/suricata.service.d/ea-nfqueue.conf <<'UNIT'
[Service]
Type=simple
ExecStart=
ExecStart=/usr/bin/suricata -c /etc/suricata/suricata-ea.yaml -q 0
Restart=on-failure
UNIT
systemctl daemon-reload
systemctl enable nginx suricata
systemctl restart suricata
systemctl is-active --quiet suricata
# Nginx terminates traffic locally: queue INPUT/OUTPUT, not routed FORWARD packets.
# Retain established packets too. queue-bypass is the documented lab fail-open policy.
IFS=',' read -r -a alb_cidrs <<< "$ALB_SUBNET_CIDRS"
for cidr in "${alb_cidrs[@]}"; do
  iptables -C INPUT -s "$cidr" -p tcp --dport 8080 -j NFQUEUE --queue-num 0 --queue-bypass 2>/dev/null ||
    iptables -I INPUT -s "$cidr" -p tcp --dport 8080 -j NFQUEUE --queue-num 0 --queue-bypass
  iptables -C OUTPUT -d "$cidr" -p tcp --sport 8080 -j NFQUEUE --queue-num 0 --queue-bypass 2>/dev/null ||
    iptables -I OUTPUT -d "$cidr" -p tcp --sport 8080 -j NFQUEUE --queue-num 0 --queue-bypass
done
netfilter-persistent save
systemctl restart nginx
curl --fail --silent --show-error http://127.0.0.1:8080/health
dpkg-query -W nginx libnginx-mod-http-modsecurity modsecurity-crs suricata > /opt/ea-bootstrap/installed-web.tsv
echo "EA WEB installation complete; end-to-end and IPS verdict tests are still required"

/bin/bash "$BOOTSTRAP_DIR/velociraptor.sh"
