"""Download immutable S3 versions and verify a case. No AWS calls in verify mode."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile

def relative_key(case_id, key):
    prefix = 'cases/'+case_id+'/'
    if not key.startswith(prefix) or '\\' in key or ':' in key or any(p in ('','..','.') for p in key.split('/')):
        raise ValueError('Unsafe or foreign case object key')
    return PurePosixPath(key[len(prefix):])

def file_hash(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

def verify(root):
    root=Path(root).resolve()
    manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    case=manifest['case_id']
    if not re.fullmatch(r'CASE-[A-Za-z0-9_-]{1,59}',case): raise ValueError('Invalid case ID')
    if manifest.get('schema_version') not in ('1.0','1.1'): raise ValueError('Unsupported manifest schema')
    jobs=manifest.get('jobs')
    if not isinstance(jobs,list) or not jobs: raise ValueError('Manifest has no evidence objects')
    paths=set()
    for item in jobs:
        relative=relative_key(case,item['key'])
        path=(root/relative).resolve()
        if not path.is_relative_to(root) or not path.is_file(): raise ValueError('Missing or unsafe evidence path')
        normalized=str(path).casefold()
        if normalized in paths: raise ValueError('Duplicate destination path')
        paths.add(normalized)
        if item.get('status')!='verified' or not re.fullmatch('[a-f0-9]{64}',item.get('sha256','')):
            raise ValueError('Unverified manifest entry')
        if path.stat().st_size!=item['size_bytes'] or file_hash(path)!=item['sha256']:
            raise ValueError('Evidence hash/size mismatch: '+str(relative))
    return {'case_id':case,'verified_objects':len(jobs),'manifest_sha256':file_hash(root/'manifest.json'),
        'integrity':manifest['integrity'],'bytes_verified':True}

def download(s3,bucket,case,destination,manifest_version=None):
    if not re.fullmatch(r'CASE-[A-Za-z0-9_-]{1,59}',case): raise ValueError('Invalid case ID')
    destination=Path(destination).resolve()
    if destination.exists():
        # A failed prior download is never reported as a successful export.
        report=verify(destination)
        receipt=json.loads((destination/'export-verification.json').read_text(encoding='utf-8'))
        if report['case_id']!=case or receipt.get('source_bucket')!=bucket:
            raise ValueError('Existing export belongs to another case or bucket')
        if manifest_version and receipt.get('source_manifest_version')!=manifest_version:
            raise ValueError('Existing export is a different manifest version')
        if receipt.get('manifest_sha256')!=report['manifest_sha256']:
            raise ValueError('Export receipt does not match the manifest')
        return report
    args={'Bucket':bucket,'Key':f'cases/{case}/manifest.json'}
    if manifest_version: args['VersionId']=manifest_version
    response=s3.get_object(**args)
    manifest_body=response['Body'].read(4*1024*1024+1)
    response['Body'].close()
    if len(manifest_body)>4*1024*1024: raise ValueError('Manifest exceeds size limit')
    if not response.get('VersionId') or response['VersionId']=='null':
        raise ValueError('Manifest must have an immutable version')
    manifest=json.loads(manifest_body)
    if manifest['case_id']!=case or not manifest.get('jobs'): raise ValueError('Wrong or empty case manifest')
    size=sum(item['size_bytes'] for item in manifest['jobs'])
    destination.parent.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(destination.parent).free<size+128*1024*1024: raise ValueError('Insufficient local space')
    with tempfile.TemporaryDirectory(prefix='.ea-export-',dir=destination.parent) as staging:
        staging=Path(staging)
        (staging/'manifest.json').write_bytes(manifest_body)
        for item in manifest['jobs']:
            relative=relative_key(case,item['key'])
            path=staging/relative
            if path.exists(): raise ValueError('Colliding object paths')
            locator=item.get('destination',{})
            if locator.get('bucket')!=bucket or locator.get('key')!=item['key'] or not locator.get('version_id'):
                raise ValueError('Immutable final object locator is required')
            path.parent.mkdir(parents=True,exist_ok=True)
            args={'Bucket':bucket,'Key':item['key'],'VersionId':locator['version_id']}
            obj=s3.get_object(**args)
            with path.open('xb') as f:
                try:
                    received=0
                    while block:=obj['Body'].read(1024*1024):
                        received+=len(block)
                        if received>item['size_bytes']:raise ValueError('Object exceeds manifest size')
                        f.write(block)
                finally: obj['Body'].close()
        report=verify(staging)
        report['source_manifest_version']=response['VersionId']
        report['source_bucket']=bucket
        (staging/'export-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        # Destination absence checked above; same-volume rename exposes only a complete verified bundle.
        staging.rename(destination)
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    v=sub.add_parser('verify'); v.add_argument('directory',type=Path)
    d=sub.add_parser('download'); d.add_argument('case_id'); d.add_argument('directory',type=Path)
    d.add_argument('--bucket',required=True); d.add_argument('--profile',required=True)
    d.add_argument('--region',default='ap-northeast-2'); d.add_argument('--manifest-version')
    a=p.parse_args()
    if a.command=='verify': result=verify(a.directory)
    else:
        import boto3
        result=download(boto3.Session(profile_name=a.profile,region_name=a.region).client('s3'),
            a.bucket,a.case_id,a.directory,a.manifest_version)
    print(json.dumps(result,indent=2))
    return 0

if __name__=='__main__': raise SystemExit(main())
