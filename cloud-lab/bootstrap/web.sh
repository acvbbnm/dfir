#!/bin/bash
set -euo pipefail

source /dev/stdin <<< "$(curl -s http://169.254.169.254/latest/meta-data/instance-id || true)"

/bin/bash "$(dirname "$0")/base.sh" || true

export DEBIAN_FRONTEND=noninteractive

# Nginx
apt-get install -y nginx
systemctl enable nginx

# Suricata
add-apt-repository -y ppa:oisf/suricata-stable
apt-get update -y
apt-get install -y suricata

# NFQUEUE inline 설정
cat > /etc/suricata/suricata-ea.yaml << 'SURICATA_CONF'
%YAML 1.1
---
vars:
  address-groups:
    HOME_NET: "[10.60.0.0/16]"
    EXTERNAL_NET: "!$HOME_NET"

nfq:
  - mode: accept
    id: 0
    fail-open: yes

outputs:
  - eve-log:
      enabled: yes
      filetype: regular
      filename: /var/log/suricata/eve.json
      types:
        - alert
        - http
        - dns
        - tls
        - flow
        - stats:
            enabled: yes
            totals: yes
            threads: no
SURICATA_CONF

# iptables NFQUEUE — ALB→WEB 양방향
iptables -I FORWARD -i ens5 -p tcp --dport 8080 -j NFQUEUE --queue-num 0
iptables -I FORWARD -o ens5 -p tcp --sport 8080 -j NFQUEUE --queue-num 0

# 영구화
apt-get install -y iptables-persistent
netfilter-persistent save

# Nginx reverse proxy 설정
cat > /etc/nginx/sites-available/default << 'NGINX_CONF'
server {
    listen 8080;
    server_name _;

    location /health {
        return 200 'ok';
        add_header Content-Type text/plain;
    }

    location / {
        proxy_pass http://APP_PRIVATE_IP:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    access_log /var/log/nginx/access.log combined;
    error_log /var/log/nginx/error.log warn;
}
NGINX_CONF

systemctl restart suricata
systemctl restart nginx

echo "EA WEB setup complete"
