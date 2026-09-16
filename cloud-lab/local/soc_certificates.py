from pathlib import Path
import subprocess
p=Path('/tmp/ea-soc-tls');p.mkdir(exist_ok=True)
def run(*args):subprocess.run(args,cwd=p,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
run('openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','2','-subj','/CN=EA Local SOC CA','-keyout','ca.key','-out','ca.pem')
run('openssl','req','-newkey','rsa:2048','-nodes','-subj','/CN=ea-ready-soc','-keyout','soc.key','-out','soc.csr')
(p/'soc.ext').write_text('subjectAltName=DNS:ea-ready-soc,DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=serverAuth,clientAuth\n')
run('openssl','x509','-req','-in','soc.csr','-CA','ca.pem','-CAkey','ca.key','-CAcreateserial','-out','soc.pem','-days','2','-extfile','soc.ext')
(p/'soc.key').chmod(0o644)
