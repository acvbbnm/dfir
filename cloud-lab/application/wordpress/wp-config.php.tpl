<?php
/**
 * WordPress 설정 템플릿 — 배포 시 Secrets Manager에서 값을 읽어 치환한다.
 * 직접 편집하지 말고, bootstrap/app.sh에서 envsubst 또는 sed로 치환.
 */

define('DB_NAME',     '${DB_NAME}');
define('DB_USER',     '${DB_USER}');
define('DB_PASSWORD', '${DB_PASSWORD}');
define('DB_HOST',     '${DB_HOST}');
define('DB_CHARSET',  'utf8mb4');
define('DB_COLLATE',  '');

$table_prefix = 'wp_';

define('AUTH_KEY',         '${AUTH_KEY}');
define('SECURE_AUTH_KEY',  '${SECURE_AUTH_KEY}');
define('LOGGED_IN_KEY',    '${LOGGED_IN_KEY}');
define('NONCE_KEY',        '${NONCE_KEY}');
define('AUTH_SALT',        '${AUTH_SALT}');
define('SECURE_AUTH_SALT', '${SECURE_AUTH_SALT}');
define('LOGGED_IN_SALT',   '${LOGGED_IN_SALT}');
define('NONCE_SALT',       '${NONCE_SALT}');

define('WP_DEBUG', false);
define('WP_DEBUG_LOG', false);
define('DISALLOW_FILE_EDIT', true);

define('FORCE_SSL_ADMIN', true);
if (isset($_SERVER['HTTP_X_FORWARDED_PROTO']) && $_SERVER['HTTP_X_FORWARDED_PROTO'] === 'https') {
    $_SERVER['HTTPS'] = 'on';
}

define('WP_HOME',    '${WP_URL}');
define('WP_SITEURL', '${WP_URL}');

if (!defined('ABSPATH')) {
    define('ABSPATH', __DIR__ . '/');
}

require_once ABSPATH . 'wp-settings.php';
