"""Offline import of verified case bundles. Never executes or extracts evidence.

CloudTrail records/JSONL values are preserved, including unknown fields. ZIP
members have independent hashes plus their parent's immutable object locator.
Shared resource/request references express correlation, never causal claims.
"""
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import zipfile
from .model import dumps, timestamp, uid
from .store import Store

LIMIT=64*1024*1024
CASE_LIMIT=256*1024*1024

def bounded(stream, limit=LIMIT):
    value=stream.read(limit+1)
    if len(value)>limit:raise ValueError('Evidence exceeds import byte limit')
    return value

def members(name,body):
    if body[:4]==b'PK\x03\x04':
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            entries=[x for x in archive.infolist() if not x.is_dir()]
            if len(entries)>10000 or sum(x.file_size for x in entries)>CASE_LIMIT:
                raise ValueError('ZIP expansion exceeds import budget')
            seen=set()
            for entry in entries:
                if entry.filename in seen:raise ValueError('Duplicate ZIP member name')
                seen.add(entry.filename)
                if entry.file_size>LIMIT:raise ValueError('Oversized ZIP member')
                # No extract(): malicious member paths cannot write any file.
                with archive.open(entry) as f:yield name+'!/'+entry.filename,bounded(f),entry.filename
    elif body[:2]==b'\x1f\x8b':
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as f:yield name+'!gunzip',bounded(f),name
    else:yield name,body,name

def rows(body):
    try:text=body.decode('utf-8-sig')
    except UnicodeDecodeError:return
    try:
        parsed=json.loads(text)
        items=parsed.get('Records') if isinstance(parsed,dict) else parsed
        if isinstance(items,list):
            for item in items:
                if isinstance(item,dict):yield dumps(item),item
                else:yield dumps({'value':item}),{'value':item}
        elif isinstance(parsed,dict):yield text,parsed
        else:yield dumps({'value':parsed}),{'value':parsed}
    except json.JSONDecodeError:
        for line in text.splitlines():
            if not line.strip():continue
            try:item=json.loads(line)
            except json.JSONDecodeError:item={'text':line}
            if isinstance(item,dict):yield line if 'text' not in item else dumps(item),item
            else:yield dumps({'value':item}),{'value':item}

def describe(row,name):
    """Return derived interpretation without replacing any original field."""
    raw=row.get('eventTime') or row.get('@timestamp') or row.get('timestamp') or row.get('time')
    kind='cloud_record';time_kind='event_recorded'
    title=row.get('eventName') or row.get('event_type') or row.get('action') or name.rsplit('/',1)[-1]
    if row.get('eventSource') and row.get('eventTime'):kind='cloudtrail_event'
    elif '/Processes.json' in name or '%2FProcesses.json' in name:
        kind='linux_process_snapshot';raw=None;time_kind='collection_observed'
        title=str(row.get('Name') or row.get('Exe') or 'Process snapshot')
    elif 'modsecurity' in name:
        kind='waf_event';title='ModSecurity audit'
        tx=row.get('transaction')
        if isinstance(tx,dict):raw=tx.get('time_stamp')  # No timezone is supplied by this producer; do not assume UTC.
    elif 'nginx' in name and 'request_id' in row:
        kind='web_request';title=f"{row.get('method','')} {row.get('url','')} · {row.get('status','')}"
    elif 'wp-audit' in name:kind='application_audit'
    if not isinstance(raw,str):raw=None
    return kind,raw,time_kind,str(title)

def ingest_cloud(bundle,database,allow_partial=False):
    root=Path(bundle).resolve();manifest_path=root/'manifest.json'
    if manifest_path.stat().st_size>4*1024*1024:raise ValueError('Oversized manifest')
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    case=manifest['case_id'];jobs=manifest.get('jobs',[])
    if not re.fullmatch(r'CASE-[A-Za-z0-9_-]{1,59}',case):raise ValueError('Invalid case ID')
    if manifest.get('schema_version')!='1.1':raise ValueError('Immutable source manifest v1.1 required')
    if manifest.get('integrity')!='PASS' and not (allow_partial and manifest.get('integrity')=='PARTIAL'):
        raise ValueError('Bundle is not PASS; partial evidence requires --allow-partial')
    if not jobs or len(jobs)>10000:raise ValueError('Empty or oversized manifest')
    if any(not isinstance(j.get('size_bytes'),int) or not 0<=j['size_bytes']<=LIMIT for j in jobs):
        raise ValueError('Invalid object size')
    if sum(j['size_bytes'] for j in jobs)>CASE_LIMIT:raise ValueError('Case import byte budget exceeded')
    checked=[];seen=set();prefix=f'cases/{case}/'
    for job in jobs:
        key=job['key']
        if not key.startswith(prefix) or '\\' in key or ':' in key or any(x in ('','..','.') for x in key.split('/')):
            raise ValueError('Unsafe or foreign case object')
        path=(root/PurePosixPath(key[len(prefix):])).resolve()
        if not path.is_relative_to(root) or str(path).casefold() in seen:raise ValueError('Unsafe or duplicate path')
        seen.add(str(path).casefold())
        loc=job.get('destination',{})
        if job.get('status')!='verified' or not loc.get('version_id') or loc['version_id']=='null' or loc.get('key')!=key:
            raise ValueError('Unverified object or missing immutable locator')
        with path.open('rb') as f:body=bounded(f)
        if len(body)!=job['size_bytes'] or hashlib.sha256(body).hexdigest()!=job['sha256']:
            raise ValueError('Evidence hash/size mismatch')
        checked.append((job,path,body))
    target=manifest.get('target',{});account=target.get('account_id','unknown');region=target.get('region','unknown')
    resource=target.get('instance_id') or target.get('rds_id') or target.get('role_arn')
    store=Store(database);counts={'case_id':case,'sources':0,'records':0,'integrity':manifest['integrity']}
    try:
        with store.db:
            store.db.execute('INSERT OR IGNORE INTO cases VALUES (?,?)',(case,case))
            for job,path,body in checked:
                for relative,payload,member in members(job['key'][len(prefix):],body):
                    if member.endswith(('.index','.db','.png','.jpg','.exe')):continue
                    digest=hashlib.sha256(payload).hexdigest()
                    scope='cloud:'+account+':'+region+':'+job['sha256']
                    source=uid('source',case,relative,digest)
                    if store.db.execute('SELECT 1 FROM sources WHERE id=?',(source,)).fetchone():continue
                    context={'target':target,'scope':scope,'parent_sha256':job['sha256'],
                        'source_locator':job.get('source'),'original_locator':job.get('original_locator'),'destination_locator':job['destination'],
                        'member':member,'manifest_integrity':manifest['integrity']}
                    store.db.execute('INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                        (source,case,relative,str(path),digest,len(payload),'cloud_bundle','complete',0,None,dumps(context),'1'))
                    count=0
                    for count,(raw,row) in enumerate(rows(payload),1):
                        if counts['records']>=300000:raise ValueError('Record budget exceeded')
                        record=uid('record',source,count);kind,when,time_kind,title=describe(row,member)
                        tm=timestamp(when,'unknown')
                        store.db.execute('INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?)',
                            (record,source,count,raw,kind,resource,scope,tm['time_raw'],tm['time_utc']))
                        observation=store.node(case,'Observation',record,title,
                            {'record_id':record,'kind':kind,'time_kind':time_kind,'host':resource,'scope':scope,'title':title,**tm})
                        record_account=row.get('recipientAccountId') or account
                        record_region=row.get('awsRegion') or region
                        refs=[]
                        if resource:refs.append(('CloudResource',f'{account}:{region}:{resource}',resource,'target_context'))
                        for ref in row.get('resources',[]) if isinstance(row.get('resources',[]),list) else []:
                            if isinstance(ref,dict) and ref.get('ARN'):refs.append(('CloudResource',ref['ARN'],ref['ARN'],'explicit_resource'))
                        request=row.get('request_id') or row.get('requestID')
                        if kind=='waf_event' and isinstance(row.get('transaction'),dict):
                            request=row['transaction'].get('unique_id') or request
                        if isinstance(request,str) and 0<len(request)<=256:
                            namespace='aws-api' if kind=='cloudtrail_event' else 'web-generated'
                            refs.append(('RequestReference',f'{record_account}:{record_region}:{namespace}:{request}',request,'shared_request_id'))
                        for label,identity,display,basis in refs:
                            node=store.node(case,label,identity,display,{'account_id':record_account,'region':record_region})
                            store.edge(case,observation,node,'REFERENCES',record,basis)
                        counts['records']+=1
                    store.db.execute('UPDATE sources SET rows_count=? WHERE id=?',(count,source))
                    counts['sources']+=1
        return counts
    finally:store.close()
