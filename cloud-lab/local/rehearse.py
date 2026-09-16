"""Isolated Linux WAF/collector checks; only loopback HTTP requests are generated."""
import http.server
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time
import urllib.request
import urllib.error
import sys
import zipfile

def run(*args):
    p=subprocess.run(args,capture_output=True,text=True)
    if p.returncode: raise RuntimeError(' '.join(args)+': '+p.stderr[-3000:])
    return p.stdout

def main():
    root=Path(__file__).resolve().parents[1]
    hits=[]
    class Backend(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200); self.end_headers(); self.wfile.write(b'backend-ok')
        def log_message(self,*args): pass
    backend=http.server.ThreadingHTTPServer(('127.0.0.1',18080),Backend)
    threading.Thread(target=backend.serve_forever,daemon=True).start()
    conf=(root/'application/nginx/default.conf').read_text().replace('APP_PRIVATE_IP:8080','127.0.0.1:18080').replace('ALB_TRUST_DIRECTIVES','set_real_ip_from 10.60.1.0/24;')
    Path('/etc/nginx/sites-available/default').write_text(conf)
    run('nginx','-t'); run('nginx')
    def request(path):
        req=urllib.request.Request('http://127.0.0.1:8080'+path,headers={'Host':'portal.lab','User-Agent':'EA-local-rehearsal'})
        try:
            with urllib.request.urlopen(req,timeout=5) as r: return r.status,r.headers.get('X-Request-ID')
        except urllib.error.HTTPError as e: return e.code,e.headers.get('X-Request-ID')
    assert request('/?q=normal')[0]==200
    attack='/?id=1%27%20OR%20%271%27=%271&ea_run=local-waf'
    assert request(attack)[0]==200
    time.sleep(.1)
    audit=Path('/var/log/modsecurity/audit.json')
    assert audit.exists() and '942' in audit.read_text()
    path=Path('/etc/modsecurity/ea.conf')
    path.write_text(path.read_text().replace('SecRuleEngine DetectionOnly','SecRuleEngine On'))
    run('nginx','-t'); run('nginx','-s','quit')
    for _ in range(50):
        if not Path('/run/nginx.pid').exists():break
        time.sleep(.1)
    run('nginx')
    count=len(hits)
    status,request_id=request(attack)
    assert status==403, status
    assert len(hits)==count, 'WAF-blocked request reached backend'
    assert request('/?q=normal')[0]==200
    statuses=[request('/wp-login.php')[0] for _ in range(14)]
    assert 429 in statuses
    records=[json.loads(line) for line in Path('/var/log/nginx/access.json').read_text().splitlines()]
    assert any(r['request_id']==request_id and r['status']==403 for r in records)
    print('PASS actual ModSecurity/CRS: DetectionOnly=200, On=403, backend not reached, normal=200, rate=429',flush=True)
    Path('/etc/suricata/rules').mkdir(parents=True,exist_ok=True)
    shutil.copy(root/'application/suricata/local.rules','/etc/suricata/rules/local.rules')
    run('suricata','-T','-c',str(root/'application/suricata/suricata-ea.yaml'))
    print('PASS actual Suricata configuration load (inline verdict not tested here)',flush=True)
    for php in (root/'application').rglob('*.php'): run('php','-l',str(php))
    engine=Path('/tmp/ea-velociraptor'); shutil.copy('/artifacts/velociraptor',engine); engine.chmod(0o700)
    output=Path('/tmp/triage.zip')
    print(run(str(engine),'version'),flush=True)
    run(str(engine),'--definitions',str(root/'collectors'),'artifacts','collect','Custom.EA.LinuxTriage','--output',str(output))
    with zipfile.ZipFile(output) as z:
        names=z.namelist()
        print(json.dumps({'collector_members':names[:30]}),flush=True)
        assert any('Processes' in n for n in names)
        assert any('nginx' in n for n in names)
    print('PASS actual Velociraptor collection ZIP with process and raw web logs',flush=True)
    print(run('dpkg-query','-W','nginx','libnginx-mod-http-modsecurity','libmodsecurity3t64','modsecurity-crs','suricata','php8.3-cli'),flush=True)
    run('nginx','-s','quit'); backend.shutdown()

if __name__=='__main__': main()
