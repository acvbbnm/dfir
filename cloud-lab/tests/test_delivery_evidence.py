import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from test_local_runtime import load

ROOT=Path(__file__).resolve().parents[1]

def test_nested_flat_alert_identity_and_no_host_id_guess(monkeypatch):
    m=load(ROOT/'collectors/alert_collector.py')
    base={'_id':'alert/'+'x'*200,'_source':{'host':{'id':'not-an-ec2-id'},'kibana.alert.rule.name':'SQLi','@timestamp':'2026-09-15T00:00:00Z'}}
    a=json.loads(m.alert_to_event(base)['Detail'])
    assert a['target']['type']=='unknown' and 'instance_id' not in a['target']
    assert len(a['case_id'])<64 and a['rule_name']=='SQLi'
    base['_source']['cloud']={'provider':'aws','instance':{'id':'i-0123456789abcdef0'},'account':{'id':'111111111111'},'region':'ap-northeast-2'}
    assert json.loads(m.alert_to_event(base)['Detail'])['target']['type']=='ec2'

def test_partial_publish_retries_only_failed_and_raises(monkeypatch):
    m=load(ROOT/'collectors/alert_collector.py');client=MagicMock()
    monkeypatch.setattr(m,'EVENT_BUS','arn:aws:events:ap-northeast-2:222222222222:event-bus/ea')
    monkeypatch.setattr(m.boto3,'client',lambda *a,**k:client);monkeypatch.setattr(m.time,'sleep',lambda _:None)
    client.put_events.side_effect=[{'Entries':[{'EventId':'ok'},{'ErrorCode':'fail'}]}]+[{'Entries':[{'ErrorCode':'fail'}]}]*3
    with pytest.raises(RuntimeError):m.publish_events([{'x':1},{'x':2}])
    assert client.put_events.call_args_list[1].kwargs['Entries']==[{'x':2}]

def test_failed_poll_does_not_advance_and_closes_pit(monkeypatch):
    m=load(ROOT/'collectors/alert_collector.py');saved=[];calls=[]
    monkeypatch.setattr(m,'load_cursor',lambda:None);monkeypatch.setattr(m,'save_cursor',saved.append)
    def es(method,path,**kwargs):
        calls.append((method,path,kwargs))
        return {'id':'pit'} if path.endswith('/_pit') and method=='POST' else {'hits':{'hits':[{'_id':'a','_source':{},'sort':[1]}]}}
    monkeypatch.setattr(m,'es',es)
    def fail(_):raise RuntimeError('delivery failed')
    monkeypatch.setattr(m,'publish_events',fail)
    with pytest.raises(RuntimeError):m.run_once()
    assert not saved and calls[-1][:2]==('DELETE','/_pit')
    assert calls[1][2]['json']['sort']==[{'_shard_doc':'asc'}]

def test_failed_manifest_schema_can_record_zero_objects():
    import jsonschema
    schema=json.loads((ROOT/'collectors/schemas/manifest.schema.json').read_text(encoding='utf-8'))
    d={'schema_version':'1.1','case_id':'CASE-empty','finalized_at':'2026-09-15T00:00:00Z','integrity':'FAIL','jobs':[]}
    jsonschema.validate(d,schema)
    d['integrity']='PASS'
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(d,schema)

def test_original_copy_is_version_locked_and_records_locator(monkeypatch):
    from datetime import datetime,timezone
    m=load(ROOT/'infra/automation/lambda_src/collect_aws_logs/handler.py')
    monkeypatch.setenv('CLOUDTRAIL_BUCKET','original');monkeypatch.setenv('WORKLOAD_ACCOUNT_ID','111111111111')
    s3=MagicMock();s3.get_paginator.return_value.paginate.return_value=[{'Contents':[{'Key':'source.gz','Size':10}]}]
    s3.head_object.return_value={'VersionId':'v-original','ContentLength':10};s3.copy_object.return_value={'VersionId':'v-copy'}
    date=datetime(2026,9,15,tzinfo=timezone.utc)
    objects,errors=m.capture_originals(s3,'CASE-test',date,date)
    assert not errors and objects[0]['source']['version_id']=='v-original'
    assert s3.copy_object.call_args.kwargs['CopySource']['VersionId']=='v-original'

def test_existing_export_wrong_case_rejected(tmp_path,monkeypatch):
    m=load(ROOT/'scripts/evidence_bundle.py')
    monkeypatch.setattr(m,'verify',lambda _:dict(case_id='CASE-other',manifest_sha256='a'))
    (tmp_path/'export-verification.json').write_text(json.dumps({'source_bucket':'b','manifest_sha256':'a'}))
    with pytest.raises(ValueError,match='another case'):m.download(None,'b','CASE-test',tmp_path)
