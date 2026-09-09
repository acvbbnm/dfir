#!/bin/bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

apt-get update -y
apt-get upgrade -y

timedatectl set-timezone Asia/Seoul

apt-get install -y \
  curl wget unzip jq \
  apt-transport-https \
  ca-certificates \
  gnupg \
  auditd audispd-plugins

systemctl enable auditd
systemctl start auditd

cat > /etc/audit/rules.d/ea-exec.rules << 'AUDIT_RULES'
-a always,exit -F arch=b64 -S execve -k ea-exec
-a always,exit -F arch=b32 -S execve -k ea-exec
-w /etc/ -p wa -k ea-config
-w /var/log/ -p wa -k ea-log-tamper
AUDIT_RULES

augenrules --load

cat > /etc/sysctl.d/99-ea-hardening.conf << 'SYSCTL'
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.send_redirects = 0
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv4.conf.all.log_martians = 1
net.ipv4.icmp_echo_ignore_broadcasts = 1
SYSCTL

sysctl --system

echo "EA base setup complete"
