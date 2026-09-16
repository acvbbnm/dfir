"""Actual MySQL 8.4/PHP application checks in the isolated Linux network."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time
import pymysql

def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def run(*args):
    r=subprocess.run(args,check=True,text=True,capture_output=True)
    print(r.stdout.strip());return r.stdout
ca='/tmp/ea-db-tls/ca.pem'
settings=dict(host='ea-ready-db',user='root',password='local-rehearsal-only',ssl_ca=ca,
    ssl_verify_cert=True,ssl_verify_identity=True,autocommit=True)
for attempt in range(45):
    try:db=pymysql.connect(**settings);break
    except pymysql.MySQLError:
        if attempt==44:raise
        time.sleep(1)
apps=[dict(host='ea-ready-db',port=3306,username=name+'_user',password='local-'+name+'-only',dbname=name) for name in ('wordpress','dvwa')]
init=load('init','/src/scripts/initialize_database.py');init.provision(db,apps);init.provision(db,apps)
with db.cursor() as c:
    c.execute('SELECT VERSION()');print('MySQL version:',c.fetchone()[0])
    c.execute('CREATE TABLE IF NOT EXISTS dvwa.users(user_id INT PRIMARY KEY,first_name VARCHAR(15),last_name VARCHAR(15),user VARCHAR(15),password VARCHAR(32),avatar VARCHAR(70),last_login TIMESTAMP,failed_login INT)')
    c.execute("INSERT IGNORE INTO dvwa.users VALUES(1,'admin','admin','admin',MD5('local-training-only'),'',NOW(),0)")
    c.execute('CREATE TABLE IF NOT EXISTS dvwa.guestbook(comment_id SMALLINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,comment VARCHAR(300),name VARCHAR(100))')
for secret in apps:
    params={**settings,'user':secret['username'],'password':secret['password'],'database':secret['dbname']}
    connection=pymysql.connect(**params)
    try:
        with connection.cursor() as c:
            other='dvwa' if secret['dbname']=='wordpress' else 'wordpress'
            try:c.execute('USE '+other)
            except pymysql.MySQLError:pass
            else:raise AssertionError('Cross-application database access permitted')
    finally:connection.close()
try:pymysql.connect(host='ea-ready-db',user=apps[0]['username'],password=apps[0]['password'],ssl_disabled=True)
except pymysql.MySQLError:print('PASS non-TLS database connection rejected')
else:raise AssertionError('Plaintext DB connection accepted')
bad={**settings,'ssl_ca':'/etc/ssl/certs/ca-certificates.crt'}
try:pymysql.connect(**bad)
except pymysql.MySQLError:print('PASS untrusted CA rejected')
else:raise AssertionError('Invalid CA accepted')

for app in ('wordpress','dvwa'):
    root=Path('/var/www')/app;root.mkdir(parents=True,exist_ok=True)
    with tarfile.open('/artifacts/'+app+'.tar.gz') as t:
        # Extract trusted, hash-locked upstream fixture into a fresh local test container.
        for member in t.getmembers():
            parts=Path(member.name).parts
            if len(parts)<2:continue
            member.name=str(Path(*parts[1:]));t.extract(member,root,filter='data')
wordpress=load('wp','/src/bootstrap/configure_wordpress.py')
root=Path('/var/www/wordpress');(root/'wp-config.php').write_text(wordpress.render_config(apps[0],'https://localhost'))
file=root/'wp-includes/class-wpdb.php';text=file.read_text();needle='$this->dbh = mysqli_init();'
assert text.count(needle)==1
file.write_text(text.replace(needle,needle+"\nmysqli_ssl_set($this->dbh,null,null,'"+ca+"',null,null);"))
(root/'wp-content/mu-plugins').mkdir(exist_ok=True)
shutil.copy('/src/application/wordpress/mu-plugins/ea-audit.php',root/'wp-content/mu-plugins/ea-audit.php')
Path('/var/log/wp-audit').mkdir(exist_ok=True)
run('php','/src/application/wordpress/initialize.php');run('php','/src/application/wordpress/initialize.php')
with db.cursor() as c:
    c.execute("SELECT COUNT(*) FROM wordpress.wp_users WHERE user_login LIKE 'ea-user-%'");assert c.fetchone()[0]==20
    c.execute("SELECT COUNT(*) FROM wordpress.wp_posts WHERE post_name LIKE 'ea-training-post-%'");assert c.fetchone()[0]==50
dvwa=load('dvwa','/src/bootstrap/configure_dvwa.py');dvwa.configure('/var/www/dvwa',apps[1],ca)
run('php','-l','/var/www/dvwa/dvwa/includes/dvwaPage.inc.php')
run('php','-l','/var/www/dvwa/config/config.inc.php')
check=Path('/tmp/check-dvwa.php')
check.write_text("<?php $_SERVER['HTTP_HOST']='dvwa.lab'; $_SERVER['SERVER_NAME']='dvwa.lab'; define('DVWA_WEB_PAGE_TO_ROOT','/var/www/dvwa/'); require '/var/www/dvwa/dvwa/includes/dvwaPage.inc.php'; dvwaDatabaseConnect(); echo 'PASS DVWA mysqli and PDO verified TLS connection';")
assert 'PASS DVWA mysqli and PDO verified TLS connection' in run('php',str(check))
print('PASS dedicated database isolation; idempotent WordPress setup; DVWA TLS')
db.close()
