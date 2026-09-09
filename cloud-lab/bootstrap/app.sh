#!/bin/bash
set -euo pipefail

/bin/bash "$(dirname "$0")/base.sh" || true

export DEBIAN_FRONTEND=noninteractive

# PHP 8.3
add-apt-repository -y ppa:ondrej/php
apt-get update -y
apt-get install -y \
  apache2 \
  libapache2-mod-fcgid \
  php8.3-fpm php8.3-mysql php8.3-xml php8.3-mbstring \
  php8.3-curl php8.3-zip php8.3-gd php8.3-intl \
  php8.3-bcmath php8.3-imagick

# Apache 모듈
a2enmod proxy_fcgi setenvif rewrite headers
a2enconf php8.3-fpm

# WordPress 다운로드
mkdir -p /var/www/wordpress
cd /var/www/wordpress
curl -sO https://wordpress.org/latest.tar.gz
tar xzf latest.tar.gz --strip-components=1
rm latest.tar.gz
chown -R www-data:www-data /var/www/wordpress

# mu-plugins 디렉터리
mkdir -p /var/www/wordpress/wp-content/mu-plugins
mkdir -p /var/log/wp-audit
chown www-data:www-data /var/log/wp-audit

# Apache VirtualHost
cat > /etc/apache2/sites-available/wordpress.conf << 'APACHE_CONF'
<VirtualHost *:8080>
    ServerName _
    DocumentRoot /var/www/wordpress

    <Directory /var/www/wordpress>
        AllowOverride All
        Require all granted
    </Directory>

    <FilesMatch \.php$>
        SetHandler "proxy:unix:/run/php/php8.3-fpm.sock|fcgi://localhost"
    </FilesMatch>

    <Directory /var/www/wordpress/wp-content/uploads>
        php_admin_flag engine off
        <FilesMatch "\.(php|phtml|php3|php4|php5|phps)$">
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

# PHP-FPM 보안
cat > /etc/php/8.3/fpm/pool.d/www-security.conf << 'PHP_SEC'
[www]
php_admin_value[open_basedir] = /var/www/wordpress:/tmp:/var/log/wp-audit
php_admin_value[disable_functions] = exec,passthru,shell_exec,system,proc_open,popen
php_admin_flag[allow_url_fopen] = off
PHP_SEC

systemctl restart php8.3-fpm
systemctl restart apache2

echo "EA APP setup complete"
