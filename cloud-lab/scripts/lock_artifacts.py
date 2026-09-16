"""Resolve official releases once, hash downloaded bytes, and reuse the committed lock."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]

def read(url):
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'EvidenceAtlas-preparation'}),timeout=60) as r:
        return r.read()

def download(url,target,expected=None):
    sha=hashlib.sha256()
    part=target.with_suffix(target.suffix+'.part')
    if target.exists():
        with target.open('rb') as f:
            for b in iter(lambda:f.read(1024*1024),b''): sha.update(b)
        if expected and sha.hexdigest()!=expected: raise ValueError('Cached artifact hash mismatch')
        return sha.hexdigest()
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'EvidenceAtlas-preparation'}),timeout=90) as r, part.open('wb') as f:
        while b:=r.read(1024*1024): sha.update(b); f.write(b)
    digest=sha.hexdigest()
    if expected and digest!=expected: raise ValueError('Official release digest mismatch')
    part.replace(target)
    return digest

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--refresh',action='store_true',help='Explicitly resolve new versions; never run during apply')
    p.add_argument('--cache',type=Path,default=ROOT.parent/'.runtime/cloud-artifacts')
    a=p.parse_args(); a.cache.mkdir(parents=True,exist_ok=True)
    path=ROOT/'artifacts.lock.json'
    if path.exists() and not a.refresh:
        lock=json.loads(path.read_text(encoding='utf-8'))
    else:
        wordpress=json.loads(read('https://api.wordpress.org/core/version-check/1.7/'))['offers'][0]['current']
        velo=json.loads(read('https://api.github.com/repos/Velocidex/velociraptor/releases/latest'))
        asset=next(x for x in velo['assets'] if x['name'].endswith('-linux-amd64'))
        artifacts={
            'wordpress':{'version':wordpress,'url':f'https://wordpress.org/wordpress-{wordpress}.tar.gz','filename':'wordpress.tar.gz','license':'GPL-2.0-or-later'},
            'velociraptor':{'version':velo['tag_name'],'url':asset['browser_download_url'],'filename':'velociraptor','sha256':asset['digest'].removeprefix('sha256:'),'hash_source':'GitHub release digest','license':'AGPL-3.0'},
        }
        for name,repo,ref in [('dvwa','digininja/DVWA','2.5'),('cloudgoat','RhinoSecurityLabs/cloudgoat','v2.5.0')]:
            commit=json.loads(read(f'https://api.github.com/repos/{repo}/commits/{ref}'))['sha']
            artifacts[name]={'version':ref,'commit':commit,'url':f'https://codeload.github.com/{repo}/tar.gz/{commit}','filename':name+'.tar.gz','license':'GPL-3.0' if name=='dvwa' else 'BSD-3-Clause'}
        ca='https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem'
        artifacts['rds_ca']={'version':'downloaded-'+datetime.now(timezone.utc).date().isoformat(),'url':ca,'filename':'rds-ca.pem','purpose':'RDS TLS trust bundle'}
        elastic='8.19.20'
        agent_url=f'https://artifacts.elastic.co/downloads/beats/elastic-agent/elastic-agent-{elastic}-linux-x86_64.tar.gz'
        checksum=read(agent_url+'.sha512').decode().split()[0]
        if len(checksum)!=128: raise ValueError('Invalid official Agent SHA512')
        lock={'schema_version':'1.0','resolved_at':datetime.now(timezone.utc).isoformat(),
            'elastic':{'version':elastic,'agent_url':agent_url,'agent_sha512':checksum,'checksum_url':agent_url+'.sha512',
                       'installation':'Signed Elastic APT repository; exact stack version'},
            'ubuntu_container':'ubuntu@sha256:224a1869083a311ef3f13648a154ba79832fbef6364d31493642ca03082da254',
            'artifacts':artifacts}
    for name,item in lock['artifacts'].items():
        print('Resolving '+name,flush=True)
        item['sha256']=download(item['url'],a.cache/item['filename'],item.get('sha256'))
        item.setdefault('hash_source','SHA256 computed over HTTPS download; not an independent signature')
    path.write_text(json.dumps(lock,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print('Official artifacts cached and locked')

if __name__=='__main__': main()
