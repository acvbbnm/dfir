"""Generate throwaway certificates for the isolated local MySQL rehearsal."""
from pathlib import Path
import subprocess

p=Path('/tmp/ea-db-tls');p.mkdir(exist_ok=True)
def run(*args):subprocess.run(args,cwd=p,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
run('openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','2','-subj','/CN=EA Local Test CA','-keyout','ca.key','-out','ca.pem')
run('openssl','req','-newkey','rsa:2048','-nodes','-subj','/CN=ea-ready-db','-keyout','server.key','-out','server.csr')
(p/'server.ext').write_text('subjectAltName=DNS:ea-ready-db\nextendedKeyUsage=serverAuth\n')
run('openssl','x509','-req','-in','server.csr','-CA','ca.pem','-CAkey','ca.key','-CAcreateserial','-out','server.pem','-days','2','-extfile','server.ext')
(p/'server.key').chmod(0o644)  # Throwaway local-only key, readable by MySQL container uid.
print('Created isolated rehearsal CA/server certificate')
