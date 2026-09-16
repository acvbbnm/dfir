"""PIT pagination, overlap replay and at-least-once EventBridge delivery.

PIT shard cursors are never reused across polls. Only a completed poll advances
the UTC watermark; failed/ambiguous sends replay and are deduplicated downstream.
"""
import hashlib
import json
import logging
import os
import platform
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse
import boto3
import requests

logger = logging.getLogger('ea-alert-collector')
ES_URL = os.environ.get('ES_URL', 'https://localhost:9200').rstrip('/')
ES_API_KEY = os.environ.get('ES_API_KEY', '')
ES_CA = os.environ.get('ES_CA', True)
SPACE = os.environ.get('KIBANA_SPACE', 'default')
POLL_INTERVAL = int(os.environ.get('POLL_INTERVAL', '30'))
REGION = os.environ.get('REGION', 'ap-northeast-2')
SECURITY_ACCOUNT_ID = os.environ.get('SECURITY_ACCOUNT_ID', '')
EVENT_BUS = os.environ.get('EVENT_BUS', '')  # Cross-account bus must be its full ARN.
CURSOR_FILE = os.environ.get('CURSOR_FILE', '/var/lib/ea-collector/cursor.json')
OVERLAP = int(os.environ.get('OVERLAP_SECONDS', '900'))
BACKFILL = int(os.environ.get('BACKFILL_HOURS', '24'))

def field(source, dotted, default=None):
    if dotted in source:
        return source[dotted]
    parts=dotted.split('.')
    for length in range(len(parts)-1,0,-1):
        prefix='.'.join(parts[:length])
        if prefix in source and isinstance(source[prefix],dict):
            return field(source[prefix],'.'.join(parts[length:]),default)
    return default

def load_cursor():
    path=Path(CURSOR_FILE)
    if not path.exists(): return None
    data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('space_id') != SPACE or data.get('es_url') != ES_URL:
        raise ValueError('Cursor belongs to another ES/space; use a separate cursor file')
    return data.get('watermark')

def save_cursor(watermark):
    path=Path(CURSOR_FILE);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    with temporary.open('w',encoding='utf-8') as f:
        json.dump(dict(watermark=watermark,space_id=SPACE,es_url=ES_URL),f)
        f.flush();os.fsync(f.fileno())
    os.replace(temporary,path)

def es(method,path,**kwargs):
    endpoint=urlparse(ES_URL)
    if endpoint.scheme!='https' and endpoint.hostname not in ('localhost','127.0.0.1','::1'):
        raise ValueError('Remote Elasticsearch requires HTTPS')
    response=requests.request(method,ES_URL+path,headers={'Authorization':'ApiKey '+ES_API_KEY},
        timeout=30,verify=ES_CA,**kwargs)
    response.raise_for_status()
    return response.json()

def alert_to_event(hit):
    source=hit['_source'];get=lambda key,default=None:field(source,key,default)
    instance=get('cloud.instance.id')
    provider=get('cloud.provider')
    account=get('cloud.account.id');region=get('cloud.region')
    target={'type':'unknown','account_id':account,'region':region}
    if provider=='aws' and isinstance(instance,str) and re.fullmatch(r'i-[a-f0-9]{8,17}',instance):
        if account and region:
            target.update(type='ec2',instance_id=instance)
    # host.id is an OS/agent identity, never an EC2 instance identity.
    identity=f'{SPACE}#{hit["_id"]}#1.0'
    detail={'schema_version':'1.1','case_id':'CASE-'+hashlib.sha256(identity.encode()).hexdigest()[:48],
        'alert_id':hit['_id'],'rule_id':get('kibana.alert.rule.uuid',''),
        'rule_name':get('kibana.alert.rule.name','unknown'),'space_id':SPACE,'playbook_version':'1.0',
        'severity':get('kibana.alert.severity',get('kibana.alert.rule.severity','medium')),
        'detected_at':get('@timestamp',''),'target':target,
        'source_indices':get('kibana.alert.rule.parameters.index',[]),
        'signal_fields':{k:get(k) for k in ('source.ip','destination.ip','url.path','process.name','event.action') if get(k) is not None},
        'collector':{'host':platform.node(),'source_index':hit.get('_index'),
                     'collected_at':datetime.now(timezone.utc).isoformat()}}
    return {'Source':'evidence-atlas.alert-collector','DetailType':'SecurityAlertCollected',
        'EventBusName':EVENT_BUS,'Detail':json.dumps(detail,ensure_ascii=False)}

def publish_events(entries):
    if not entries:return
    if not re.fullmatch(r'arn:aws:events:[a-z0-9-]+:[0-9]{12}:event-bus/[A-Za-z0-9_.-]+',EVENT_BUS):
        raise ValueError('EVENT_BUS must be the Security account bus ARN')
    client=boto3.client('events',region_name=REGION)
    for offset in range(0,len(entries),10):
        pending=entries[offset:offset+10]
        for attempt in range(4):
            response=client.put_events(Entries=pending)
            outcomes=response.get('Entries',[])
            if len(outcomes)!=len(pending):raise RuntimeError('Incomplete EventBridge response')
            pending=[entry for entry,result in zip(pending,outcomes)
                     if result.get('ErrorCode') or not result.get('EventId')]
            if not pending:break
            if attempt<3:time.sleep(2**attempt)
        if pending:raise RuntimeError('EventBridge publish failed; watermark retained for replay')

def run_once():
    watermark=load_cursor();end=datetime.now(timezone.utc)
    start=(datetime.fromisoformat(watermark.replace('Z','+00:00'))-timedelta(seconds=OVERLAP)
           if watermark else end-timedelta(hours=BACKFILL))
    pit=es('POST','/.alerts-security.alerts-'+quote(SPACE,safe='')+'/_pit',params={'keep_alive':'2m'})['id']
    cursor=None;count=0
    try:
        for _ in range(1000):
            body={'size':100,'pit':{'id':pit,'keep_alive':'2m'},'sort':[{'_shard_doc':'asc'}],
                'track_total_hits':False,'query':{'range':{'@timestamp':{'gte':start.isoformat(),'lte':end.isoformat()}}}}
            if cursor:body['search_after']=cursor
            data=es('POST','/_search',json=body)
            pit=data.get('pit_id',pit)
            if data.get('timed_out') or data.get('_shards',{}).get('failed',0):
                raise RuntimeError('Incomplete Elasticsearch search; watermark retained')
            hits=data.get('hits',{}).get('hits',[])
            if not hits:
                save_cursor(end.isoformat());return count
            publish_events([alert_to_event(hit) for hit in hits])
            cursor=hits[-1]['sort'];count+=len(hits)
        raise RuntimeError('Poll page budget exhausted; run a smaller explicit backfill')
    finally:
        try:es('DELETE','/_pit',json={'id':pit})
        except Exception:logger.warning('Could not close PIT; it will expire')

def main():
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    while True:
        try:logger.info('Delivered %d alerts (overlap may replay)',run_once())
        except KeyboardInterrupt:return
        except Exception:logger.exception('Poll failed')
        time.sleep(POLL_INTERVAL)

if __name__=='__main__':main()
