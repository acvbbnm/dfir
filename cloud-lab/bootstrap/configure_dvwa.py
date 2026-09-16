"""Install dedicated DVWA configuration and narrow TLS patches to locked source."""
import base64
import json
import os
from pathlib import Path

def configure(root,secret,ca='/etc/ssl/certs/ea-rds-ca.pem'):
    root=Path(root)
    if secret['dbname']!='dvwa' or secret['username'] in ('root','admin','wordpress_user'):
        raise ValueError('DVWA requires its own database and user')
    encoded=base64.b64encode(json.dumps(secret).encode()).decode()
    config="<?php\n$ea=json_decode(base64_decode('"+encoded+"'),true);\n"+r"""
$DBMS='MySQL';
$_DVWA=[];
foreach (['server'=>'host','database'=>'dbname','user'=>'username','password'=>'password','port'=>'port'] as $key=>$value) {
    $_DVWA['db_'.$key]=$ea[$value];
}
unset($ea);
$_DVWA['recaptcha_public_key']=''; $_DVWA['recaptcha_private_key']='';
$_DVWA['default_security_level']='impossible'; $_DVWA['default_locale']='en';
define('MYSQL','mysql'); define('SQLITE','sqlite');
$_DVWA['disable_authentication']=false; $_DVWA['SQLI_DB']=MYSQL;
require_once __DIR__.'/ea-tls.php';
"""
    (root/'config/config.inc.php').write_text(config)
    (root/'config/config.inc.php').chmod(0o640)
    # The CA path is fixed installation configuration, not a request parameter.
    phpca=json.dumps(ca)
    (root/'config/ea-tls.php').write_text("""<?php
function ea_dvwa_connect($host,$user,$password,$db='',$port=3306) {
    $conn=mysqli_init();
    mysqli_ssl_set($conn,NULL,NULL,"""+phpca+""",NULL,NULL);
    mysqli_real_connect($conn,$host,$user,$password,$db,(int)$port,NULL,MYSQLI_CLIENT_SSL);
    return $conn;
}
""")
    for name in ('dvwa/includes/dvwaPage.inc.php','dvwa/includes/DBMS/MySQL.php'):
        file=root/name;text=file.read_text()
        if 'mysqli_connect(' not in text and 'ea_dvwa_connect(' not in text:raise ValueError('DVWA source drift: '+name)
        text=text.replace('mysqli_connect(', 'ea_dvwa_connect(')
        if name.endswith('dvwaPage.inc.php') and 'PDO::MYSQL_ATTR_SSL_CA' not in text:
            needle="$_DVWA[ 'db_user' ], $_DVWA[ 'db_password' ]);"
            if needle not in text:raise ValueError('DVWA PDO source drift')
            text=text.replace(needle,"$_DVWA[ 'db_user' ], $_DVWA[ 'db_password' ], [PDO::MYSQL_ATTR_SSL_CA => "+phpca+", PDO::MYSQL_ATTR_SSL_VERIFY_SERVER_CERT => true] );")
        file.write_text(text)

def main():
    import boto3
    client=boto3.client('secretsmanager',region_name=os.environ['AWS_REGION'])
    secret=json.loads(client.get_secret_value(SecretId=os.environ['DVWA_APP_SECRET_ARN'])['SecretString'])
    configure('/var/www/dvwa',secret)

if __name__=='__main__':main()
