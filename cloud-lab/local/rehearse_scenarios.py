"""Disposable ea-ready-soc integration only: real queries/aggregations and triage ZIP."""
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import urllib.parse
import zipfile
import uuid
import requests

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

prepare=load('prepare','/src/siem/prepare.py')
logs=load('cloud_logs','/src/collectors/cloud_logs.py')
collector=load('host_collect','/src/collectors/host_collect.py')
ca='/tmp/ea-soc-tls/ca.pem'
suffix=uuid.uuid4().hex[:12]
cloud_index='logs-ea.aws-scenario'+suffix
web_index='logs-ea.wordpress-scenario'+suffix
session=requests.Session();session.auth=('elastic','local-rehearsal-only');session.verify=ca
def es(method,path,body=None):
    r=session.request(method,'https://ea-ready-soc:9200'+path,json=body,timeout=60)
    r.raise_for_status();return r.json()

fixtures=[('iam.amazonaws.com','CreateUser'),('cloudtrail.amazonaws.com','StopLogging'),
    ('rds.amazonaws.com','ModifyDBSnapshotAttribute'),('ec2.amazonaws.com','ModifySnapshotAttribute'),
    ('s3.amazonaws.com','DeleteObject'),('secretsmanager.amazonaws.com','GetSecretValue'),
    ('ec2.amazonaws.com','RunInstances'),('lambda.amazonaws.com','Invoke')]
fixtures += [('s3.amazonaws.com','GetObject')]*100
stamp=datetime.now(timezone.utc).isoformat()
source={'region':'ap-northeast-2','account_id':'111111111111','kind':'cloudtrail'}
for n,(provider,action) in enumerate(fixtures+[('unrelated.example','CreateUser')]):
    raw={'eventTime':stamp,'eventName':action,'eventSource':provider,'awsRegion':'us-east-1',
         'recipientAccountId':'111111111111','userIdentity':{'principalId':'fixture-role:fixture-session'},
         'requestParameters':{'attribute':{'arbitrary':n}},'eventID':str(n)}
    _,doc=logs.event(json.dumps(raw),raw,{'bucket':'LOCAL_NOT_AWS','key':str(n),'version_id':'fixture'},source,1)
    es('POST','/'+cloud_index+'/_doc?op_type=create',doc)
es('POST','/'+cloud_index+'/_refresh')
plan=prepare.build('https://ea-ready-soc',Path(ca).read_text())
for step in plan:
    rule=step['body']
    if step['path']!='/api/detection_engine/rules' or rule.get('language')!='lucene':continue
    result=es('POST','/'+cloud_index+'/_search',{'size':0,'query':{'query_string':{'query':rule['query']}},
        'aggs':{'actors':{'terms':{'field':'user.id'}}}})
    expected=100 if rule['rule_id']=='ea-s3-read-burst' else 1
    assert result['hits']['total']['value']==expected,(rule['rule_id'],result)
    assert result['aggregations']['actors']['buckets'][0]['doc_count']==expected
    print('PASS real query and keyword aggregation',rule['rule_id'],expected,flush=True)

body={'docs':[{'_source':{'message':json.dumps({'timestamp':stamp,'action':'login_failed','attempted_user':'fixture-user'})}}]}
doc=es('POST','/_ingest/pipeline/ea-raw-v1/_simulate',body)['docs'][0]['doc']['_source']
assert doc['user']['name']=='fixture-user' and doc['event']['action']=='login_failed'
doc['event']['dataset']='ea.wordpress'
for _ in range(10):es('POST','/'+web_index+'/_doc?op_type=create',doc)
es('POST','/'+web_index+'/_refresh')
result=es('POST','/'+web_index+'/_search',{'size':0,'query':{'term':{'event.action':'login_failed'}},
    'aggs':{'users':{'terms':{'field':'user.name'}}}})
assert result['aggregations']['users']['buckets'][0]['doc_count']==10
print('PASS WordPress ingest and actual username threshold aggregation',flush=True)

# Do not enable or execute the synthetic persistence files.
paths=['/etc/cron.d/ea-scenario-fixture','/etc/systemd/system/ea-scenario-fixture.service','/root/.ssh/authorized_keys']
for name in paths:
    path=Path(name);path.parent.mkdir(parents=True,exist_ok=True)
    marker='# Evidence Atlas inert scenario fixture\n'
    if path.exists() and path.read_text()!=marker:raise RuntimeError('Unrelated fixture exists; use a fresh container')
    if not path.exists():path.write_text(marker)
engine=Path('/tmp/ea-scenario-velociraptor');shutil.copy('/artifacts/velociraptor',engine);engine.chmod(0o700)
output=Path('/tmp/ea-scenario-triage.zip')
report=collector.collect(output,engine,Path('/src/collectors'),hashlib.sha256(engine.read_bytes()).hexdigest())
with zipfile.ZipFile(output) as z:
    names={urllib.parse.unquote(n):n for n in z.namelist()}
    rows=[json.loads(line) for line in z.read(names['results/Custom.EA.LinuxTriage/Logs.json']).decode().splitlines()]
    collected={str(row['OSPath']):row for row in rows}
    for name in paths:
        assert name in collected,(name,collected.keys())
        assert collected[name].get('Upload') and not collected[name]['Upload'].get('error')
assert collector.collect(output,engine,Path('/src/collectors'),hashlib.sha256(engine.read_bytes()).hexdigest())==report
print('PASS actual persistence originals, raw metadata, ZIP hash and idempotent retry',flush=True)
print(json.dumps({'scope':'LOCAL_DOCKER_NOT_AWS','profile':report['profile'],'sha256':report['sha256'],'size_bytes':report['size_bytes']}),flush=True)
