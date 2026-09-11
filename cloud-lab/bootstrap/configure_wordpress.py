"""Render PHP safely from a least-privilege application secret; never log secret values."""
import base64
import json
import os
from pathlib import Path
import secrets

import boto3


def render_config(secret: dict, url: str) -> str:
    required = ('username', 'password', 'host', 'dbname')
    if any(not isinstance(secret.get(k), str) or not secret[k] for k in required):
        raise ValueError('WordPress secret is missing required string fields')
    if secret['username'].lower() in {'admin', 'root'}:
        raise ValueError('WordPress must use a dedicated DB user')
    if not url.startswith('https://') or any(c in url for c in '\r\n'):
        raise ValueError('WP_URL must use HTTPS')
    values = {
        'DB_NAME': secret['dbname'], 'DB_USER': secret['username'],
        'DB_PASSWORD': secret['password'],
        'DB_HOST': f"{secret['host']}:{int(secret.get('port', 3306))}",
        'DB_CHARSET': 'utf8mb4', 'DB_COLLATE': '', 'WP_HOME': url, 'WP_SITEURL': url,
    }
    for name in ('AUTH_KEY', 'SECURE_AUTH_KEY', 'LOGGED_IN_KEY', 'NONCE_KEY',
                 'AUTH_SALT', 'SECURE_AUTH_SALT', 'LOGGED_IN_SALT', 'NONCE_SALT'):
        values[name] = secrets.token_urlsafe(48)
    encoded = base64.b64encode(json.dumps(values).encode()).decode('ascii')
    return "<?php\n" + f"$ea = json_decode(base64_decode('{encoded}'), true);\n" + """
foreach ($ea as $key => $value) { define($key, $value); }
unset($ea, $key, $value);
$table_prefix = 'wp_';
define('MYSQL_CLIENT_FLAGS', MYSQLI_CLIENT_SSL);
define('WP_DEBUG', false);
define('DISALLOW_FILE_EDIT', true);
define('DISALLOW_FILE_MODS', true);
define('FORCE_SSL_ADMIN', true);
if (($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https') { $_SERVER['HTTPS'] = 'on'; }
if (!defined('ABSPATH')) { define('ABSPATH', __DIR__ . '/'); }
require_once ABSPATH . 'wp-settings.php';
"""


def main():
    target = Path('/var/www/wordpress/wp-config.php')
    if target.exists():
        return  # Preserve salts and config on a repeated installation.
    client = boto3.client('secretsmanager', region_name=os.environ['AWS_REGION'])
    response = client.get_secret_value(SecretId=os.environ['WP_APP_SECRET_ARN'])
    config = render_config(json.loads(response['SecretString']), os.environ['WP_URL'])
    temporary = target.with_suffix('.php.new')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(config)
    temporary.replace(target)


if __name__ == '__main__':
    main()
