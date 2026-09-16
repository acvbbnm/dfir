"""Regression checks for scenario review findings; never contact AWS."""
import copy
from datetime import datetime,timezone
import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from test_local_runtime import load

ROOT=Path(__file__).resolve().parents[1]

def test_new_scenario_answers_and_invalid_ids():
    schema=json.loads((ROOT/'scenarios/schemas/answer.schema.json').read_text(encoding='utf-8'))
    validator=load(ROOT/'scripts/scenario_records.py').answer_validator()
    answer={'run_id':'test','executed_at':'2026-09-16T00:00:00Z','targets':[{'resource_type':'fixture','resource_id':'synthetic'}],'expected_evidence':{}}
    ids=['N0']+[f'{p}{n}' for p,count in [('W',5),('H',3),('C',3),('I',4),('D',4),('E',3),('X',2),('K',11)] for n in range(1,count+1)]
    assert len(ids)==36
    for sid in ids+[f'S{i}' for i in range(7)]:validator.validate(dict(answer,scenario_id=sid))
    for sid in ('K12','S7','W0','x1','../N0'):
        with pytest.raises(ValidationError):validator.validate(dict(answer,scenario_id=sid))
    with pytest.raises(ValidationError):validator.validate(dict(answer,scenario_id='N0',executed_at='yesterday'))

def test_answer_conversion_keeps_observation_and_refuses_plan():
    m=load(ROOT/'scripts/scenario_records.py')
    receipt={'executed':True,'scenario_id':'S3','run_id':'r1','executed_at':'2026-09-16T00:00:00Z',
        'target':'https://10.60.1.10','actions':[['GET','/probe',None]],
        'results':[{'method':'GET','path':'/probe','status':403,'timestamp':'2026-09-16T00:00:01Z','body_sha256':'b'*64}]}
    expected={'expected_results':['blocked'],'expected_evidence':{'waf':['CRS match']},'policy_versions':{'waf':'On/rev1'}}
    original=copy.deepcopy(receipt);answer=m.convert(receipt,expected,'a'*64)
    assert receipt==original and answer['assessment_status']=='unreviewed'
    assert answer['actions'][0]['expected_result']=='blocked'
    assert answer['coverage']['waf']['blocked']=='not_evaluated'
    assert answer['execution_complete']
    with pytest.raises(ValueError,match='offline plan'):m.convert(dict(receipt,executed=False),expected,'a'*64)
    with pytest.raises(ValueError,match='every planned'):m.convert(receipt,dict(expected,expected_results=[]),'a'*64)
    receipt['results'][0]['path']='/different'
    with pytest.raises(ValueError,match='order'):m.convert(receipt,expected,'a'*64)

def test_accounts_and_regions_in_actual_collector_configuration():
    m=load(ROOT/'bootstrap/configure_collectors.py')
    sources=m.sources('ea','111111111111','222222222222','ap-northeast-2',['us-west-2'])['sources']
    ct=[s for s in sources if s['kind']=='cloudtrail']
    assert len(ct)==6
    assert {(s['account_id'],s['region']) for s in ct}=={(a,r) for a in ('111111111111','222222222222') for r in ('ap-northeast-2','us-east-1','us-west-2')}
    assert all('/'+s['region']+'/' in s['prefix'] and s['account_id'] in s['prefix'] for s in ct)

def test_cloudtrail_normalization_preserves_native_region_and_raw():
    m=load(ROOT/'collectors/cloud_logs.py')
    raw={'eventTime':'2026-09-16T01:02:03Z','eventName':'SetDefaultPolicyVersion','eventSource':'iam.amazonaws.com',
         'awsRegion':'us-east-1','recipientAccountId':'222222222222','errorCode':'AccessDenied',
         'userIdentity':{'principalId':'role:session','arn':'arn:test'},'requestParameters':{'versionId':'v2'}}
    before=copy.deepcopy(raw)
    _,doc=m.event(json.dumps(raw),raw,{'key':'source','version_id':'v1'},
        {'region':'ap-northeast-2','account_id':'111111111111','kind':'cloudtrail'},1)
    assert raw==before and doc['ea']['raw']==before
    assert doc['cloud']['region']=='us-east-1' and doc['cloud']['account']['id']=='222222222222'
    assert doc['event']['provider']=='iam.amazonaws.com' and doc['event']['outcome']=='failure'
    assert doc['ea']['audit']['parameters']=={'versionId':'v2'}

def scope(monkeypatch):
    monkeypatch.setenv('WORKLOAD_ACCOUNT_ID','111111111111');monkeypatch.setenv('SECURITY_ACCOUNT_ID','222222222222')
    monkeypatch.setenv('CLOUDTRAIL_BUCKET','original');monkeypatch.setenv('EVIDENCE_KMS_KEY_ARN','fixture-key')
    monkeypatch.delenv('AUDIT_EXTRA_REGIONS',raising=False)

def test_originals_capture_global_iam_and_continues_after_failed_prefix(monkeypatch):
    scope(monkeypatch);m=load(ROOT/'infra/automation/lambda_src/collect_aws_logs/handler.py')
    s3=MagicMock()
    def pages(**kw):
        prefix=kw['Prefix']
        if '111111111111/CloudTrail/ap-northeast-2' in prefix:raise RuntimeError('fixture denied')
        return [{'Contents':[{'Key':prefix+'event.gz','Size':5}]}] if '222222222222/CloudTrail/us-east-1' in prefix else [{}]
    s3.get_paginator.return_value.paginate.side_effect=pages
    s3.head_object.return_value={'VersionId':'original-v1','ContentLength':5};s3.copy_object.return_value={'VersionId':'copy-v1'}
    date=datetime(2026,9,16,tzinfo=timezone.utc)
    objects,errors=m.capture_originals(s3,'CASE-test',date,date)
    assert len(objects)==1 and objects[0]['region']=='us-east-1'
    assert objects[0]['account_id']=='222222222222' and errors
    assert s3.copy_object.call_args.kwargs['CopySource']['VersionId']=='original-v1'

def test_lookup_includes_global_principal_events_without_ec2_filter(monkeypatch):
    scope(monkeypatch);m=load(ROOT/'infra/automation/lambda_src/collect_aws_logs/handler.py');calls=[]
    def client(service,**kw):
        c=MagicMock()
        if service=='sts':c.assume_role.return_value={'Credentials':{'AccessKeyId':'fixture','SecretAccessKey':'fixture','SessionToken':'fixture'}}
        else:
            calls.append((kw,c));c.get_paginator.return_value.paginate.return_value=[{'Events':[{'EventId':'fixture-global','CloudTrailEvent':'{}'}]}]
        return c
    monkeypatch.setattr(m.boto3,'client',client)
    date=datetime(2026,9,16,tzinfo=timezone.utc);records,errors=m.lookup_derivative(date,date)
    assert not errors and len(records)==4
    assert {r['lookup_region'] for r in records}=={'ap-northeast-2','us-east-1'}
    assert all('LookupAttributes' not in c.get_paginator.return_value.paginate.call_args.kwargs for _,c in calls)

def test_rule_plan_matches_new_normalized_fields_and_is_not_causal():
    m=load(ROOT/'siem/prepare.py');plan=m.build('https://soc.example','PUBLIC-CA')
    rules=[s['body'] for s in plan if s['path']=='/api/detection_engine/rules']
    assert len(rules)==13 and len({r['rule_id'] for r in rules})==13
    iam=next(r for r in rules if r['rule_id']=='ea-iam-change')
    assert 'SetDefaultPolicyVersion' in iam['query'] and 'PassRole' not in iam['query']
    assert iam['timestamp_override']=='event.ingested' and iam['severity']=='medium'
    s3=next(r for r in rules if r['rule_id']=='ea-s3-read-burst')
    assert s3['threshold']['value']==100 and s3['threshold']['field']==['user.id']
    login=next(r for r in rules if r['rule_id']=='ea-login-burst')
    assert login['threshold']['field']==['user.name']

def test_infrastructure_event_selectors_and_rds_key():
    import hcl2
    def resources(path):
        return { (typ.strip('"'),name.strip('"')):cfg for b in hcl2.loads(path.read_text(encoding='utf-8')).get('resource',[]) for typ,names in b.items() for name,cfg in names.items() }
    ct=resources(ROOT/'infra/foundation/cloudtrail.tf')[('aws_cloudtrail','workload')]
    assert 'event_selector' not in ct and len(ct['advanced_event_selector'])==2
    text=json.dumps(ct)
    assert 'synthetic/' in text and 'AWS::S3::Object' in text and 'Invoke' in text
    rds=resources(ROOT/'infra/lab/rds.tf')[('aws_db_instance','main')]
    assert rds['kms_key_id']=='${aws_kms_key.rds.arn}'

def test_playbook_recovery_requires_expiry_and_reissuance_checks():
    r=json.loads((ROOT/'playbooks/recovery.json').read_text(encoding='utf-8'))
    steps={s['name']:s for s in r['steps']}
    assert 'verify_session_recovery_gate' in steps and 'condition' in steps['remove_emergency_policies']
    assert r['steps'].index(steps['verify_session_recovery_gate'])<r['steps'].index(steps['remove_emergency_policies'])
    containment=json.loads((ROOT/'playbooks/containment.json').read_text(encoding='utf-8'))
    assert 'no response executor' in containment['implementation']
    assert 'APP' in next(s for s in containment['steps'] if s['name']=='deregister_from_alb')['condition']
