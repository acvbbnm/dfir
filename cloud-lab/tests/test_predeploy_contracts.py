import ast
import base64
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import zipfile
from unittest.mock import MagicMock
import pytest
from test_local_runtime import load

ROOT=Path(__file__).resolve().parents[1]

def test_versioned_loader_is_small_and_checks_hash_before_writes():
    template=(ROOT/'bootstrap/load_bundle.sh.tpl').read_text()
    settings=dict(role='soc',region='ap-northeast-2',bucket='ea-bootstrap-111111111111',key='soc/'+'a'*64+'.json',version_id='v'*256,sha256='a'*64)
    script=template.replace('${settings}',base64.b64encode(json.dumps(settings).encode()).decode())
    assert len(script.encode())<16384
    python=script.split("<<'EA_BUNDLE'\n",1)[1].rsplit('EA_BUNDLE',1)[0]
    ast.parse(python)
    assert python.index('hashlib.sha256')<python.index('path.write_bytes')
    assert "VersionId=settings['version_id']" in python

def test_velociraptor_url_encoded_source_names_and_partial(tmp_path):
    m=load(ROOT/'collectors/host_collect.py');path=tmp_path/'triage.zip'
    with zipfile.ZipFile(path,'w') as z:
        for source in ('System','Processes','Connections','Logs'):
            body=json.dumps({'Upload':{'error':'File exceeds profile'}}) if source=='Logs' else '{}'
            z.writestr('results/Custom.EA.LinuxTriage%2F'+source+'.json',body)
    result=m.validate_zip(path)
    assert result['status']=='PARTIAL' and result['warnings']

def test_cloud_logs_raw_is_not_changed_by_transport_timestamp():
    m=load(ROOT/'collectors/cloud_logs.py');raw={'unknown':{'keep':1}}
    key,document=m.event('{"unknown":{"keep":1}}',raw,{'event_id':'original'},
        {'account_id':'111111111111','region':'ap-northeast-2','kind':'rds'},1,1767225600000)
    assert document['ea']['raw']==raw and 'timestamp' not in raw
    assert document['ea']['time_kind']=='event_recorded'

def test_cloud_s3_failure_does_not_mark_source_done(monkeypatch):
    m=load(ROOT/'collectors/cloud_logs.py');s3=MagicMock();state=sqlite3.connect(':memory:')
    state.execute('CREATE TABLE seen(id TEXT PRIMARY KEY)')
    s3.get_paginator.return_value.paginate.return_value=[{'Contents':[{'Key':'one.json','Size':3}]}]
    s3.head_object.return_value={'VersionId':'v1'};s3.get_object.return_value={'Body':io.BytesIO(b'{}\n')}
    monkeypatch.setattr(m,'aws_client',lambda *a:s3)
    def fail(_):raise RuntimeError('bulk partially failed')
    with pytest.raises(RuntimeError):m.collect_s3({'bucket':'b','prefix':'p','kind':'cloudtrail','account_id':'111111111111','region':'ap-northeast-2'},state,fail)
    assert state.execute('SELECT count(*) FROM seen').fetchone()[0]==0

def test_siem_paths_match_deployed_sources_and_endpoint_identity():
    m=load(ROOT/'siem/prepare.py');steps=m.build('https://soc.example','PUBLIC-CA')
    assert all('password' not in json.dumps(step).lower() for step in steps)
    policies=[s['body'] for s in steps if s['path']=='/api/fleet/package_policies']
    host=next(s['body'] for s in steps if s['path']=='/api/fleet/fleet_server_hosts')
    assert host['is_default'] and host['host_urls']==['https://soc.example:8220']
    assert any(p['name']=='ea-web-modsecurity' for p in policies)
    collector=load(ROOT/'bootstrap/configure_collectors.py')
    sources=collector.sources('ea','111111111111','222222222222','ap-northeast-2')['sources']
    assert next(s for s in sources if s['kind']=='alb')['prefix'].startswith('alb/AWSLogs/')
