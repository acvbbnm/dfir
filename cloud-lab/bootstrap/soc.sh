#!/bin/bash
set -euo pipefail

/bin/bash "$(dirname "$0")/base.sh" || true

export DEBIAN_FRONTEND=noninteractive

# 데이터 디스크 마운트 (/dev/sdf → /var/lib/elasticsearch)
if [ -b /dev/nvme1n1 ]; then
  DATA_DEV=/dev/nvme1n1
elif [ -b /dev/xvdf ]; then
  DATA_DEV=/dev/xvdf
else
  echo "WARNING: data disk not found, using root"
  DATA_DEV=""
fi

if [ -n "$DATA_DEV" ]; then
  mkfs.ext4 -F "$DATA_DEV"
  mkdir -p /var/lib/elasticsearch
  echo "$DATA_DEV /var/lib/elasticsearch ext4 defaults,nofail 0 2" >> /etc/fstab
  mount -a
fi

# Elasticsearch
wget -qO - https://artifacts.elastic.co/GPG-KEY-elasticsearch | gpg --dearmor -o /usr/share/keyrings/elastic.gpg
echo "deb [signed-by=/usr/share/keyrings/elastic.gpg] https://artifacts.elastic.co/packages/8.x/apt stable main" > /etc/apt/sources.list.d/elastic-8.x.list
apt-get update -y
apt-get install -y elasticsearch kibana

# ES 설정
cat > /etc/elasticsearch/elasticsearch.yml << 'ES_CONF'
cluster.name: ea-soc
node.name: soc-1
path.data: /var/lib/elasticsearch
network.host: 0.0.0.0
http.port: 9200
discovery.type: single-node
xpack.security.enabled: true
xpack.security.enrollment.enabled: true
xpack.security.http.ssl.enabled: false
xpack.security.transport.ssl.enabled: false
ES_CONF

# Kibana 설정
cat > /etc/kibana/kibana.yml << 'KB_CONF'
server.host: "0.0.0.0"
server.port: 5601
elasticsearch.hosts: ["http://localhost:9200"]
KB_CONF

# JVM 힙 설정 (t3.xlarge 16GB → ES에 8GB)
mkdir -p /etc/elasticsearch/jvm.options.d
cat > /etc/elasticsearch/jvm.options.d/heap.options << 'HEAP'
-Xms8g
-Xmx8g
HEAP

chown -R elasticsearch:elasticsearch /var/lib/elasticsearch

systemctl daemon-reload
systemctl enable elasticsearch kibana
systemctl start elasticsearch

# ES 시작 대기 (최대 2분)
for i in $(seq 1 24); do
  if curl -s http://localhost:9200 >/dev/null 2>&1; then
    break
  fi
  sleep 5
done

# ES 초기 비밀번호 설정
ES_PASS=$(/usr/share/elasticsearch/bin/elasticsearch-reset-password -u elastic -b -s 2>/dev/null || echo "MANUAL_SETUP_NEEDED")
echo "Elastic password: $ES_PASS" > /root/es-credentials.txt
chmod 600 /root/es-credentials.txt

# Kibana enrollment
/usr/share/elasticsearch/bin/elasticsearch-create-enrollment-token -s kibana > /root/kibana-token.txt 2>/dev/null || true
chmod 600 /root/kibana-token.txt

systemctl start kibana

echo "EA SOC setup complete"
