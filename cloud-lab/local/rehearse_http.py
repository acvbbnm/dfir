"""Validate actual Apache/FPM virtual hosts and WordPress request correlation."""
import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import time
import urllib.request

def run(*args):
    result=subprocess.run(args,text=True,capture_output=True)
    if result.returncode:raise RuntimeError(result.stderr[-2000:])
    return result.stdout
app=Path('/src/bootstrap/app.sh').read_text();dvwa=Path('/src/bootstrap/dvwa.sh').read_text()
def section(text,marker):return text.split("<<'"+marker+"'\n",1)[1].split('\n'+marker,1)[0]+'\n'
run('a2enmod','proxy_fcgi','setenvif','rewrite','headers','remoteip');run('a2enconf','php8.3-fpm')
Path('/etc/apache2/sites-available/wordpress.conf').write_text(section(app,'APACHE_CONF'))
Path('/etc/php/8.3/fpm/pool.d/www-security.conf').write_text(section(app,'PHP_SEC'))
Path('/etc/apache2/ports.conf').write_text('Listen 8080\n')
shutil.copy('/src/application/dvwa/dvwa-vhost.conf','/etc/apache2/sites-available/zzz-dvwa.conf')
Path('/etc/php/8.3/fpm/pool.d/ea-dvwa.conf').write_text(section(dvwa,'POOL'))
if subprocess.run(['id','ea-dvwa'],capture_output=True).returncode:run('useradd','--system','--home','/var/www/dvwa','--shell','/usr/sbin/nologin','ea-dvwa')
for folder in ('/var/lib/ea-dvwa/sessions','/var/lib/ea-dvwa/tmp','/var/www/dvwa/hackable/uploads'):
    Path(folder).mkdir(parents=True,exist_ok=True);run('chown','ea-dvwa:ea-dvwa',folder)
run('chown','root:ea-dvwa','/var/www/dvwa/config/config.inc.php')
run('chmod','640','/var/www/dvwa/config/config.inc.php')
run('chown','root:www-data','/var/www/wordpress/wp-config.php');run('chmod','640','/var/www/wordpress/wp-config.php')
run('chown','-R','www-data:www-data','/var/log/wp-audit')
# The deployment uses /etc/ssl/certs for RDS trust. Move the local fixture CA there too.
shutil.copy('/tmp/ea-db-tls/ca.pem','/etc/ssl/certs/ea-rds-ca.pem')
for path in ('/var/www/wordpress/wp-includes/class-wpdb.php','/var/www/dvwa/config/ea-tls.php','/var/www/dvwa/dvwa/includes/dvwaPage.inc.php'):
    p=Path(path);p.write_text(p.read_text().replace('/tmp/ea-db-tls/ca.pem','/etc/ssl/certs/ea-rds-ca.pem'))
run('a2dissite','000-default');run('a2ensite','wordpress','zzz-dvwa')
run('php-fpm8.3','-t');run('apache2ctl','configtest')
Path('/run/php').mkdir(exist_ok=True)
if Path('/run/php/php8.3-fpm.pid').exists():
    run('kill','-QUIT',Path('/run/php/php8.3-fpm.pid').read_text().strip())
    for _ in range(50):
        if not Path('/run/php/php8.3-fpm.pid').exists():break
        time.sleep(.1)
run('php-fpm8.3','-D');run('apache2ctl','start')
time.sleep(.5)
def get(path,host):
    req=urllib.request.Request('http://127.0.0.1:8080'+path,headers={'Host':host,'X-Forwarded-Proto':'https','X-Request-ID':'ea-http-check'})
    with urllib.request.urlopen(req,timeout=15) as response:return response.status,response.read().decode(errors='replace')
status,body=get('/','localhost');assert status==200 and 'Company update' in body
status,body=get('/login.php','dvwa.lab');assert status==200 and 'Damn Vulnerable' in body
# A failed login emits an audit event carrying the proxy request ID.
request=urllib.request.Request('http://127.0.0.1:8080/wp-login.php',data=b'log=ea-no-such-user&pwd=wrong',
    headers={'Host':'localhost','X-Forwarded-Proto':'https','X-Request-ID':'ea-http-check'})
with urllib.request.urlopen(request,timeout=15) as response:assert response.status==200
assert any('ea-http-check' in path.read_text() for path in Path('/var/log/wp-audit').glob('*.json'))
print('PASS real Apache/PHP-FPM WordPress and isolated DVWA HTTP responses, database TLS and audit request ID')
run('apache2ctl','stop')
run('kill','-QUIT',Path('/run/php/php8.3-fpm.pid').read_text().strip())
