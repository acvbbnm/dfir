"""Bounded S3/CloudWatch polling to SIEM with immutable provenance and replay.

Config selects exact buckets/prefix templates and log groups. S3 version IDs and
CloudWatch event IDs produce stable ES IDs. Failed bulk writes never commit state.
"""
import argparse
import gzip
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import sqlite3
import time
from datetime import datetime,timedelta,timezone
import boto3
import requests

MAX_BYTES=32*1024*1024

def parse(body):
    if body[:2]==b'\x1f\x8b':
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as f:body=f.read(MAX_BYTES+1)
    if len(body)>MAX_BYTES:raise ValueError('Log expansion limit exceeded')
    text=body.decode('utf-8')
    try:parsed=json.loads(text)
    except json.JSONDecodeError:parsed=None
    if isinstance(parsed,dict) and isinstance(parsed.get('Records'),list):
        for record in parsed['Records']:yield json.dumps(record,ensure_ascii=False),record
    else:
        for line in text.splitlines():
            if not line.strip():continue
            try:record=json.loads(line)
            except json.JSONDecodeError:record={}
            yield line,record if isinstance(record,dict) else {}

def event(original,record,locator,source,ordinal,transport_time=None):
    stamp=record.get('eventTime') or record.get('query_timestamp') or record.get('timestamp') or transport_time
    parsed_time=True
    try:
        if isinstance(stamp,(int,float)):stamp=datetime.fromtimestamp(stamp/1000,timezone.utc).isoformat()
        parsed=datetime.fromisoformat(stamp.replace('Z','+00:00'))
        if parsed.tzinfo is None:raise ValueError('No timezone')
        stamp=parsed.astimezone(timezone.utc).isoformat()
    except (ValueError,TypeError,AttributeError,OverflowError,OSError):
        stamp=datetime.now(timezone.utc).isoformat();parsed_time=False
    identity=json.dumps([locator,ordinal],sort_keys=True)
    document={'@timestamp':stamp,'event':{'original':original,'dataset':'ea.aws','ingested':datetime.now(timezone.utc).isoformat(),
        'action':record.get('eventName','log_received')},
        'data_stream':{'type':'logs','dataset':'ea.aws','namespace':'ea'},
        'cloud':{'provider':'aws','account':{'id':record.get('recipientAccountId') or source['account_id']},'region':record.get('awsRegion') or source['region']},
        'ea':{'raw':record,'locator':locator,'source_kind':source['kind'],
              'time_kind':'event_recorded' if parsed_time else 'collection_observed','ordinal':ordinal}}
    if source['kind']=='cloudtrail':
        document['event'].update(provider=record.get('eventSource','unknown'),outcome='failure' if record.get('errorCode') else 'success',kind='event')
        actor=record.get('userIdentity') or {}
        document['user']={'id':actor.get('principalId','unknown')}
        document['ea']['audit']={'actor_arn':actor.get('arn',''),
            'session_issuer':actor.get('sessionContext',{}).get('sessionIssuer',{}).get('arn',''),
            'source_address':record.get('sourceIPAddress',''), 'error_code':record.get('errorCode',''),
            'event_id':record.get('eventID',''),'event_category':record.get('eventCategory',''),
            'resource_arns':[r['ARN'] for r in record.get('resources',[]) if isinstance(r,dict) and r.get('ARN')],
            'parameters':record.get('requestParameters') or {}}
    return hashlib.sha256(identity.encode()).hexdigest(),document

def publish(documents):
    if not documents:return
    url=os.environ['ES_URL'].rstrip('/')
    if not url.startswith('https://'):raise ValueError('SIEM output requires HTTPS')
    for offset in range(0,len(documents),250):
        batch=documents[offset:offset+250];lines=[]
        for identity,document in batch:
            lines.extend([json.dumps({'create':{'_index':'logs-ea.aws-ea','_id':identity}}),json.dumps(document)])
        response=requests.post(url+'/_bulk',headers={'Authorization':'ApiKey '+os.environ['ES_API_KEY'],'Content-Type':'application/x-ndjson'},
            data='\n'.join(lines)+'\n',verify=os.environ['ES_CA'],timeout=60)
        response.raise_for_status();results=response.json().get('items',[])
        if len(results)!=len(batch) or any(x.get('create',{}).get('status') not in (201,409) for x in results):
            raise RuntimeError('SIEM bulk failed; source cursor retained')

def aws_client(service,source):
    session=boto3.Session(region_name=source['region'])
    if not source.get('role_arn'):return session.client(service)
    c=session.client('sts').assume_role(RoleArn=source['role_arn'],RoleSessionName='ea-log-reader',DurationSeconds=900)['Credentials']
    return session.client(service,aws_access_key_id=c['AccessKeyId'],aws_secret_access_key=c['SecretAccessKey'],aws_session_token=c['SessionToken'])

def collect_s3(source,state,sink=publish):
    s3=aws_client('s3',source);count=0
    for days in range(int(source.get('lookback_days',2))):
        date=(datetime.now(timezone.utc)-timedelta(days=days)).strftime('%Y/%m/%d')
        prefix=source['prefix'].replace('{date}',date)
        for page in s3.get_paginator('list_objects_v2').paginate(Bucket=source['bucket'],Prefix=prefix):
            for item in page.get('Contents',[]):
                if item['Size']==0:continue
                if item['Size']>MAX_BYTES:raise ValueError('Source object exceeds bounded log profile')
                key=item['Key'];head=s3.head_object(Bucket=source['bucket'],Key=key);version=head.get('VersionId')
                if not version or version=='null':raise ValueError('S3 log bucket requires versioning')
                identity=json.dumps([source['bucket'],key,version])
                if state.execute('SELECT 1 FROM seen WHERE id=?',(identity,)).fetchone():continue
                response=s3.get_object(Bucket=source['bucket'],Key=key,VersionId=version)
                try:body=response['Body'].read(MAX_BYTES+1)
                finally:response['Body'].close()
                if len(body)>MAX_BYTES:raise ValueError('Source exceeds read limit')
                locator={'bucket':source['bucket'],'key':key,'version_id':version,'sha256':hashlib.sha256(body).hexdigest()}
                documents=[event(raw,row,locator,source,n) for n,(raw,row) in enumerate(parse(body),1)]
                sink(documents)
                with state:state.execute('INSERT OR IGNORE INTO seen VALUES (?)',(identity,))
                count+=1
                if count>=100:return count
    return count

def collect_cloudwatch(source,state,sink=publish):
    client=aws_client('logs',source);identity=source['region']+':'+source['log_group']
    previous=state.execute('SELECT value FROM cursors WHERE id=?',(identity,)).fetchone()
    end=int(time.time()*1000)
    start=(int(previous[0])-15*60*1000) if previous else end-24*60*60*1000
    args={'logGroupName':source['log_group'],'startTime':start,'endTime':end,'limit':1000};count=0
    for _ in range(500):
        response=client.filter_log_events(**args);documents=[]
        for row in response.get('events',[]):
            locator={'log_group':source['log_group'],'log_stream':row['logStreamName'],'event_id':row['eventId'],'region':source['region']}
            try:record=json.loads(row['message'])
            except json.JSONDecodeError:record={}
            record=dict(record) if isinstance(record,dict) else {}
            documents.append(event(row['message'],record,locator,source,1,row['timestamp']))
        sink(documents);count+=len(documents)
        token=response.get('nextToken')
        if not token or token==args.get('nextToken'):
            with state:state.execute('INSERT OR REPLACE INTO cursors VALUES (?,?)',(identity,str(end)))
            return count
        args['nextToken']=token
    raise RuntimeError('CloudWatch page budget exhausted; cursor retained')

def run(config,state):
    for source in config['sources']:
        (collect_s3 if source['transport']=='s3' else collect_cloudwatch)(source,state)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True)
    p.add_argument('--state',type=Path,required=True);p.add_argument('--once',action='store_true');a=p.parse_args()
    a.state.parent.mkdir(parents=True,exist_ok=True);state=sqlite3.connect(a.state)
    state.executescript('CREATE TABLE IF NOT EXISTS seen(id TEXT PRIMARY KEY);CREATE TABLE IF NOT EXISTS cursors(id TEXT PRIMARY KEY,value TEXT NOT NULL);')
    config=json.loads(a.config.read_text())
    while True:
        try:run(config,state)
        except Exception:
            if a.once:raise
            logging.exception('Cloud log poll failed; cursor retained')
        if a.once:break
        time.sleep(60)

if __name__=='__main__':main()
