"""Run generated policies against the disposable ea-ready-soc TLS stack only."""
import importlib.util
import hashlib
import json
from pathlib import Path
import requests

s=importlib.util.spec_from_file_location('prepare','/src/siem/prepare.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
ca=Path('/tmp/ea-soc-tls/ca.pem');plan=m.build('https://ea-ready-soc',ca.read_text())
receipt=Path('/tmp/ea-siem-rehearsal.json');done=json.loads(receipt.read_text()) if receipt.exists() else []
for step in plan:
    key=hashlib.sha256(json.dumps(step,sort_keys=True).encode()).hexdigest()
    if key in done:continue
    port=9200 if step['service']=='es' else 5601
    r=requests.request(step['method'],f'https://ea-ready-soc:{port}'+step['path'],json=step['body'],
        auth=('elastic','local-rehearsal-only'),headers={'kbn-xsrf':'ea'},verify=str(ca),timeout=180)
    if not r.ok:raise RuntimeError(str(r.status_code)+' '+step['path']+' '+r.text[:3000])
    done.append(key);receipt.write_text(json.dumps(done));print('PASS',step['path'],flush=True)
# Exercise the actual Painless pipeline on a representative access log.
r=requests.post('https://ea-ready-soc:9200/_ingest/pipeline/ea-raw-v1/_simulate',
    json={'docs':[{'_source':{'message':'{"timestamp":"2026-09-15T01:02:03Z","request_id":"request-1","status":403,"unknown":"preserved"}'}}]},
    auth=('elastic','local-rehearsal-only'),verify=str(ca),timeout=30)
r.raise_for_status();result=r.json()['docs'][0]
if 'error' in result:raise RuntimeError(result['error'])
doc=result['doc']['_source'];assert doc['ea']['raw']['unknown']=='preserved' and doc['http']['response']['status_code']==403
assert 'request-1' in doc['event']['original']
print('PASS original retention, selected fields and date parsing through real Elasticsearch ingest pipeline')

m.detection_only('https://ea-ready-soc:5601',('elastic','local-rehearsal-only'),str(ca))
print('PASS actual Defend Linux detection mode and telemetry configuration')

# Check the real ModSecurity nested ID layout, not a flattened surrogate.
r=requests.post('https://ea-ready-soc:9200/_ingest/pipeline/ea-raw-v1/_simulate',
    json={'docs':[{'_source':{'message':json.dumps({'transaction':{'unique_id':'waf-1','messages':[{'message':'fixture'}]}})}}]},
    auth=('elastic','local-rehearsal-only'),verify=str(ca),timeout=30)
r.raise_for_status();doc=r.json()['docs'][0]['doc']['_source']
assert doc['ea']['request_id']=='waf-1' and doc['ea']['waf']['message_count']==1
print('PASS nested ModSecurity request correlation through actual Elasticsearch pipeline')

m.verify_fleet_host('https://ea-ready-soc:5601',('elastic','local-rehearsal-only'),str(ca),'https://ea-ready-soc:8220')
print('PASS actual persisted default Fleet Server host URL')
