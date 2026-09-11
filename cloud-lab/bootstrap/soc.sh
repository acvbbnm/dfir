#!/bin/bash
set -euo pipefail
umask 077
BOOTSTRAP_DIR="${EA_BOOTSTRAP_DIR:-/opt/ea-bootstrap}"
# shellcheck source=/dev/null
source "$BOOTSTRAP_DIR/environment.sh"
: "${ELASTIC_VERSION:?An exact Elastic version is required}"
: "${SOC_DATA_VOLUME_ID:?The dedicated SOC EBS volume ID is required}"
[[ "$ELASTIC_VERSION" =~ ^8\.[0-9]+\.[0-9]+$ ]]
/bin/bash "$BOOTSTRAP_DIR/base.sh"
export DEBIAN_FRONTEND=noninteractive
# Attachment can follow EC2 creation; wait for its serial without assuming NVMe ordering.
for attempt in $(seq 1 60); do
  if lsblk -dn -o SERIAL | tr -d '-' | grep -Fxq "${SOC_DATA_VOLUME_ID//-/}"; then break; fi
  sleep 5
done
python3 "$BOOTSTRAP_DIR/soc_disk.py"
curl --fail --silent --show-error https://artifacts.elastic.co/GPG-KEY-elasticsearch |
  gpg --batch --yes --dearmor -o /usr/share/keyrings/elastic.gpg
chmod 0644 /usr/share/keyrings/elastic.gpg
echo 'deb [signed-by=/usr/share/keyrings/elastic.gpg] https://artifacts.elastic.co/packages/8.x/apt stable main' > /etc/apt/sources.list.d/elastic-8.x.list
apt-get update -y
apt-get install -y "elasticsearch=$ELASTIC_VERSION" "kibana=$ELASTIC_VERSION"
chown elasticsearch:elasticsearch /var/lib/elasticsearch
chmod 0750 /var/lib/elasticsearch
echo 'vm.max_map_count=262144' > /etc/sysctl.d/99-ea-elasticsearch.conf
sysctl --system
SOC_IP=$(hostname -I | awk '{print $1}')
CERT_DIR=/etc/elasticsearch/ea-certs
install -d -m 0750 -o root -g elasticsearch "$CERT_DIR"
if [ ! -f "$CERT_DIR/soc/soc.crt" ]; then
  /usr/share/elasticsearch/bin/elasticsearch-certutil ca --silent --pem --out "$CERT_DIR/ca.zip"
  unzip -o -q "$CERT_DIR/ca.zip" -d "$CERT_DIR"
  /usr/share/elasticsearch/bin/elasticsearch-certutil cert --silent --pem \
    --ca-cert "$CERT_DIR/ca/ca.crt" --ca-key "$CERT_DIR/ca/ca.key" \
    --name soc --dns "localhost,$(hostname)" --ip "127.0.0.1,$SOC_IP" --out "$CERT_DIR/soc.zip"
  unzip -o -q "$CERT_DIR/soc.zip" -d "$CERT_DIR"
fi
chown -R root:elasticsearch "$CERT_DIR"
find "$CERT_DIR" -type d -exec chmod 0750 {} +
find "$CERT_DIR" -type f -exec chmod 0640 {} +
chmod 0600 "$CERT_DIR/ca/ca.key" "$CERT_DIR/ca.zip"
cat > /etc/elasticsearch/elasticsearch.yml <<'ES_CONF'
cluster.name: ea-soc
node.name: soc-1
path.data: /var/lib/elasticsearch
path.logs: /var/log/elasticsearch
network.host: 0.0.0.0
http.port: 9200
discovery.type: single-node
xpack.security.enabled: true
xpack.security.autoconfiguration.enabled: false
xpack.security.http.ssl.enabled: true
xpack.security.http.ssl.key: ea-certs/soc/soc.key
xpack.security.http.ssl.certificate: ea-certs/soc/soc.crt
xpack.security.http.ssl.certificate_authorities: [ea-certs/ca/ca.crt]
xpack.security.transport.ssl.enabled: true
xpack.security.transport.ssl.verification_mode: certificate
xpack.security.transport.ssl.key: ea-certs/soc/soc.key
xpack.security.transport.ssl.certificate: ea-certs/soc/soc.crt
xpack.security.transport.ssl.certificate_authorities: [ea-certs/ca/ca.crt]
ES_CONF
chown root:elasticsearch /etc/elasticsearch/elasticsearch.yml
chmod 0640 /etc/elasticsearch/elasticsearch.yml
# Remove auto-configuration password entries for the replaced PKCS12 settings.
for key in xpack.security.http.ssl.keystore.secure_password xpack.security.transport.ssl.keystore.secure_password xpack.security.transport.ssl.truststore.secure_password; do
  if /usr/share/elasticsearch/bin/elasticsearch-keystore list | grep -Fxq "$key"; then
    /usr/share/elasticsearch/bin/elasticsearch-keystore remove "$key"
  fi
done
printf '%s\n' '-Xms8g' '-Xmx8g' > /etc/elasticsearch/jvm.options.d/heap.options
chown root:elasticsearch /etc/elasticsearch/jvm.options.d/heap.options
chmod 0640 /etc/elasticsearch/jvm.options.d/heap.options
systemctl enable elasticsearch
systemctl restart elasticsearch
ready=false
for attempt in $(seq 1 60); do
  code=$(curl --silent --show-error --cacert "$CERT_DIR/ca/ca.crt" -o /dev/null -w '%{http_code}' https://localhost:9200 || true)
  if [ "$code" = 401 ]; then ready=true; break; fi
  sleep 5
done
[ "$ready" = true ] || { echo 'Elasticsearch TLS endpoint did not become ready' >&2; exit 1; }
install -d -m 0700 /root/ea-credentials
if [ ! -s /root/ea-credentials/elastic ]; then
  /usr/share/elasticsearch/bin/elasticsearch-reset-password -u elastic -b -s > /root/ea-credentials/elastic
fi
if [ ! -s /root/ea-credentials/kibana-service-token ]; then
  /usr/share/elasticsearch/bin/elasticsearch-service-tokens create elastic/kibana ea-kibana |
    awk '{print $NF}' > /root/ea-credentials/kibana-service-token
fi
chown root:elasticsearch /etc/elasticsearch/service_tokens
chmod 0640 /etc/elasticsearch/service_tokens
install -d -m 0750 -o root -g kibana /etc/kibana/ea-certs
install -m 0640 -o root -g kibana "$CERT_DIR/ca/ca.crt" /etc/kibana/ea-certs/ca.crt
install -m 0640 -o root -g kibana "$CERT_DIR/soc/soc.crt" /etc/kibana/ea-certs/soc.crt
install -m 0640 -o root -g kibana "$CERT_DIR/soc/soc.key" /etc/kibana/ea-certs/soc.key
cat > /etc/kibana/kibana.yml <<'KB_CONF'
server.host: "0.0.0.0"
server.port: 5601
server.ssl.enabled: true
server.ssl.certificate: /etc/kibana/ea-certs/soc.crt
server.ssl.key: /etc/kibana/ea-certs/soc.key
elasticsearch.hosts: ["https://localhost:9200"]
elasticsearch.ssl.certificateAuthorities: [/etc/kibana/ea-certs/ca.crt]
KB_CONF
chown root:kibana /etc/kibana/kibana.yml
chmod 0640 /etc/kibana/kibana.yml
export KBN_PATH_CONF=/etc/kibana
if [ ! -f /etc/kibana/kibana.keystore ]; then /usr/share/kibana/bin/kibana-keystore create --allow-root; fi
/usr/share/kibana/bin/kibana-keystore add elasticsearch.serviceAccountToken --stdin --force --allow-root < /root/ea-credentials/kibana-service-token
chown root:kibana /etc/kibana/kibana.keystore
chmod 0640 /etc/kibana/kibana.keystore
systemctl enable kibana
systemctl restart kibana
curl --fail --silent --show-error --retry 30 --retry-delay 5 --retry-all-errors \
  --cacert "$CERT_DIR/ca/ca.crt" https://localhost:5601/api/status -o /dev/null
dpkg-query -W elasticsearch kibana > /opt/ea-bootstrap/installed-soc.tsv
echo 'EA SOC TLS installation complete; Fleet policies and enrollment are Phase C tasks'
