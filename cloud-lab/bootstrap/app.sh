#!/bin/bash
set -euo pipefail
BOOTSTRAP_DIR="${EA_BOOTSTRAP_DIR:-/opt/ea-bootstrap}"
# shellcheck source=/dev/null
source "$BOOTSTRAP_DIR/environment.sh"
: "${WORDPRESS_VERSION:?An exact WordPress version is required}"
: "${WORDPRESS_SHA256:?The verified WordPress archive SHA-256 is required}"
: "${WP_APP_SECRET_ARN:?A dedicated application secret is required}"
: "${WP_URL:?WP_URL is required}"
[[ "$WORDPRESS_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
[[ "$WORDPRESS_SHA256" =~ ^[a-f0-9]{64}$ ]]
/bin/bash "$BOOTSTRAP_DIR/base.sh"
export DEBIAN_FRONTEND=noninteractive
apt-get install -y apache2 php8.3-fpm php8.3-mysql php8.3-xml php8.3-mbstring \
  php8.3-curl php8.3-zip php8.3-gd php8.3-intl
a2enmod proxy_fcgi setenvif rewrite headers
a2enconf php8.3-fpm
install -d /var/www/wordpress
if [ ! -f /var/www/wordpress/wp-includes/version.php ]; then
  archive=$(mktemp /var/tmp/ea-wordpress.XXXXXX)
  trap 'rm -f "$archive"' EXIT
  curl --fail --show-error --silent --location --proto '=https' \
    "https://wordpress.org/wordpress-${WORDPRESS_VERSION}.tar.gz" -o "$archive"
  printf '%s  %s\n' "$WORDPRESS_SHA256" "$archive" | sha256sum --check --status
  tar -xzf "$archive" --strip-components=1 --no-same-owner -C /var/www/wordpress
fi
# Normal portal code is owned by root; only uploads and audit logs are writable by PHP.
chown -R root:root /var/www/wordpress
find /var/www/wordpress -type d -exec chmod 0755 {} +
find /var/www/wordpress -type f ! -name wp-config.php -exec chmod 0644 {} +
install -d -o www-data -g www-data /var/www/wordpress/wp-content/uploads /var/log/wp-audit
install -d /var/www/wordpress/wp-content/mu-plugins
install -m 0644 "$BOOTSTRAP_DIR/application/wordpress/mu-plugins/ea-audit.php" \
  /var/www/wordpress/wp-content/mu-plugins/ea-audit.php
python3 "$BOOTSTRAP_DIR/configure_wordpress.py"
chown root:www-data /var/www/wordpress/wp-config.php
chmod 0640 /var/www/wordpress/wp-config.php
cat > /etc/apache2/sites-available/wordpress.conf <<'APACHE_CONF'
<VirtualHost *:8080>
    ServerName _
    DocumentRoot /var/www/wordpress
    <Directory /var/www/wordpress>
        AllowOverride All
        Require all granted
    </Directory>
    <FilesMatch "\.php$">
        SetHandler "proxy:unix:/run/php/php8.3-fpm.sock|fcgi://localhost"
    </FilesMatch>
    <Directory /var/www/wordpress/wp-content/uploads>
        AllowOverride None
        <FilesMatch "(?i)\.(php[0-9]?|phtml|phar|phps)$">
            Require all denied
        </FilesMatch>
    </Directory>
    ErrorLog /var/log/apache2/wordpress-error.log
    CustomLog /var/log/apache2/wordpress-access.log combined
</VirtualHost>
APACHE_CONF
a2dissite 000-default
a2ensite wordpress
sed -i 's/^Listen 80$/Listen 8080/' /etc/apache2/ports.conf
cat > /etc/php/8.3/fpm/pool.d/www-security.conf <<'PHP_SEC'
[www]
php_admin_value[open_basedir] = /var/www/wordpress:/tmp:/var/log/wp-audit:/etc/ssl/certs
php_admin_value[disable_functions] = exec,passthru,shell_exec,system,proc_open,popen
php_admin_flag[allow_url_fopen] = off
PHP_SEC
php-fpm8.3 -t
apache2ctl configtest
systemctl enable php8.3-fpm apache2
systemctl restart php8.3-fpm apache2
dpkg-query -W apache2 php8.3-fpm > /opt/ea-bootstrap/installed-app.tsv
echo "EA APP installed; provision the dedicated DB user and complete WordPress/DB TLS acceptance tests"
