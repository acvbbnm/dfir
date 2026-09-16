#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-boto3 ca-certificates
python3 - <<'EA_BUNDLE'
import base64,hashlib,json,os,pathlib,subprocess
import boto3
settings=json.loads(base64.b64decode('${settings}'))
if settings.get('version_id') in (None,'','null'):raise ValueError('Immutable bootstrap version required')
response=boto3.client('s3',region_name=settings['region']).get_object(
    Bucket=settings['bucket'],Key=settings['key'],VersionId=settings['version_id'])
try:body=response['Body'].read(1048577)
finally:response['Body'].close()
if len(body)>1048576 or hashlib.sha256(body).hexdigest()!=settings['sha256']:
    raise ValueError('Bootstrap bundle hash/size mismatch')
config=json.loads(body.decode().split('\n',1)[1])
root=pathlib.Path('/opt/ea-bootstrap');root.mkdir(mode=0o700,exist_ok=True)
for item in config['write_files']:
    path=pathlib.Path(item['path'])
    if not path.resolve().is_relative_to(root.resolve()):raise ValueError('Unsafe bootstrap path')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(base64.b64decode(item['content']));path.chmod(int(item['permissions'],8))
subprocess.run(['/bin/bash','-e',str(root/(settings['role']+'.sh'))],check=True)
EA_BUNDLE
