ARG BASE=ubuntu:24.04
FROM ${BASE}
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends nginx libnginx-mod-http-modsecurity modsecurity-crs suricata curl ca-certificates python3 python3-boto3 python3-pymysql php8.3-cli php8.3-fpm php8.3-mysql php8.3-gd apache2 unzip iproute2 procps && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/ea
COPY application /opt/ea/application
COPY bootstrap /opt/ea/bootstrap
COPY collectors /opt/ea/collectors
COPY local /opt/ea/local
RUN mkdir -p /var/log/modsecurity && chown www-data:adm /var/log/modsecurity && cp application/modsecurity/ea.conf /etc/modsecurity/ea.conf
CMD ["python3", "-c", "import time; time.sleep(86400)"]
