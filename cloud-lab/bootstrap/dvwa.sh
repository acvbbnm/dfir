#!/bin/bash
set -euo pipefail
: "${DVWA_URL:?Pinned upstream archive URL required}"
: "${DVWA_SHA256:?Pinned SHA256 required}"
[[ "$DVWA_URL" == https://codeload.github.com/digininja/DVWA/tar.gz/* ]]
[[ "$DVWA_SHA256" =~ ^[a-f0-9]{64}$ ]]
BOOTSTRAP_DIR="${EA_BOOTSTRAP_DIR:-/opt/ea-bootstrap}"
id ea-dvwa >/dev/null 2>&1 || useradd --system --home /var/www/dvwa --shell /usr/sbin/nologin ea-dvwa
install -d /var/www/dvwa
if [ ! -f /var/www/dvwa/dvwa/includes/dvwaPage.inc.php ]; then
  archive=$(mktemp /var/tmp/ea-dvwa.XXXXXX)
  trap 'rm -f "$archive"' EXIT
  curl --fail --silent --show-error --location --proto '=https' "$DVWA_URL" -o "$archive"
  printf '%s  %s\n' "$DVWA_SHA256" "$archive" | sha256sum --check --status
  tar -xzf "$archive" --strip-components=1 --no-same-owner -C /var/www/dvwa
fi
chown -R root:root /var/www/dvwa
install -d -o ea-dvwa -g ea-dvwa /var/www/dvwa/hackable/uploads /var/lib/ea-dvwa/sessions /var/lib/ea-dvwa/tmp
python3 "$BOOTSTRAP_DIR/configure_dvwa.py"
chown root:ea-dvwa /var/www/dvwa/config/config.inc.php
chmod 0640 /var/www/dvwa/config/config.inc.php
install -m 0644 "$BOOTSTRAP_DIR/application/dvwa/dvwa-vhost.conf" /etc/apache2/sites-available/zzz-dvwa.conf
cat > /etc/php/8.3/fpm/pool.d/ea-dvwa.conf <<'POOL'
[ea-dvwa]
user = ea-dvwa
group = ea-dvwa
listen = /run/php/ea-dvwa.sock
listen.owner = www-data
listen.group = www-data
listen.mode = 0660
pm = ondemand
pm.max_children = 4
pm.process_idle_timeout = 15s
php_admin_value[session.save_path] = /var/lib/ea-dvwa/sessions
php_admin_value[upload_tmp_dir] = /var/lib/ea-dvwa/tmp
php_admin_value[open_basedir] = /var/www/dvwa:/var/lib/ea-dvwa:/etc/ssl/certs
php_admin_flag[allow_url_include] = off
POOL
a2ensite zzz-dvwa
