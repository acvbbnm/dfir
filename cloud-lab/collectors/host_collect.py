"""Fixed standalone Velociraptor profile with a single scoped presigned upload."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import tempfile
import urllib.parse
import urllib.request
import zipfile

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def validate_zip(output):
    if output.stat().st_size>64*1024*1024: raise ValueError('Collection exceeds upload profile limit')
    warnings=[]
    with zipfile.ZipFile(output) as z:
        if sum(i.file_size for i in z.infolist())>256*1024*1024:raise ValueError('ZIP expansion exceeds profile limit')
        if z.testzip():raise ValueError('Collection ZIP failed CRC verification')
        names={urllib.parse.unquote(n):n for n in z.namelist()}
        for source in ('System','Processes','Connections','Logs'):
            expected='results/Custom.EA.LinuxTriage/'+source+'.json'
            if expected not in names:raise ValueError('Expected collection source missing: '+source)
        log_name=names['results/Custom.EA.LinuxTriage/Logs.json']
        lines=z.read(log_name).decode('utf-8').splitlines()
        if not lines:warnings.append('No matching raw log files were available')
        for line in lines:
            row=json.loads(line);upload_result=row.get('Upload',{})
            if isinstance(upload_result,dict) and (upload_result.get('error') or upload_result.get('Error')):
                warnings.append(str(upload_result.get('error') or upload_result.get('Error')))
    return {'sha256':sha(output),'size_bytes':output.stat().st_size,'profile':'linux-triage-v1.1',
        'status':'PARTIAL' if warnings else 'SUCCESS','warnings':warnings}

def collect(output, engine, definitions, expected):
    if sha(engine)!=expected:raise ValueError('Collector engine checksum mismatch')
    # A retry uploads the same collection instead of overwriting volatile evidence.
    if output.exists():return validate_zip(output)
    temporary=output.with_suffix('.collecting.zip')
    if temporary.exists():raise ValueError('Interrupted collection retained; inspect diagnostics before a new case')
    try:
        result=subprocess.run([str(engine),'--definitions',str(definitions),'artifacts','collect',
            'Custom.EA.LinuxTriage','--output',str(temporary)],capture_output=True,timeout=240)
    except subprocess.TimeoutExpired as exc:
        (output.parent/'collector-stderr.log').write_bytes(exc.stderr or b'Collection timed out')
        raise
    (output.parent/'collector-stderr.log').write_bytes(result.stderr)
    if result.returncode or not temporary.is_file():raise RuntimeError('Velociraptor failed; local diagnostics retained')
    report=validate_zip(temporary)
    temporary.rename(output)
    return report

def upload(path,url,bucket,region,kms_key):
    parsed=urllib.parse.urlsplit(url)
    allowed={f'{bucket}.s3.{region}.amazonaws.com',f'{bucket}.s3.amazonaws.com'}
    if parsed.scheme!='https' or parsed.hostname not in allowed or parsed.username or parsed.password:
        raise ValueError('Upload URL is not the configured evidence bucket')
    if not parsed.path.startswith('/cases/') or not parsed.query:
        raise ValueError('Upload requires a scoped signed case object URL')
    # HTTPConnection streams an open file with explicit length; URL/credentials are never printed.
    import http.client
    conn=http.client.HTTPSConnection(parsed.hostname,timeout=120,context=ssl.create_default_context())
    with path.open('rb') as data:
        conn.request('PUT',parsed.path+'?'+parsed.query,body=data,headers={
            'Content-Length':str(path.stat().st_size),'x-amz-server-side-encryption':'aws:kms',
            'x-amz-server-side-encryption-aws-kms-key-id':kms_key,
            'x-amz-meta-source-kind':'velociraptor-zip'})
        response=conn.getresponse(); response.read()
        if response.status!=200: raise RuntimeError('Evidence upload failed: HTTP '+str(response.status))
    conn.close()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case-id',required=True); p.add_argument('--output',type=Path)
    p.add_argument('--local-only',action='store_true')
    a=p.parse_args()
    if not re.fullmatch(r'CASE-[A-Za-z0-9_-]{1,59}',a.case_id): raise ValueError('Invalid case ID')
    config=json.loads(Path('/opt/ea-tools/collector-config.json').read_text())
    root=Path('/var/lib/ea-collections')/a.case_id
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    out=a.output or root/'triage.zip'
    import fcntl
    lock=(root/'collector.lock').open('a')
    fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
    report=collect(out,Path('/opt/ea-tools/velociraptor'),Path('/opt/ea-tools/artifacts'),config['sha256'])
    (out.parent/'collector-result.json').write_text(json.dumps(report),encoding='utf-8')
    if not a.local_only:
        upload(out,os.environ['SSM_UploadUrl'],config['bucket'],config['region'],config['kms_key'])
    print(json.dumps(report))

if __name__=='__main__': main()
