import hashlib
import io
import json
import zipfile
import pytest
from dfir_graph.cloud import ingest_cloud
from dfir_graph.store import Store
from dfir_graph.timeline import TimelineIndex

def bundle(tmp_path,partial=False):
    root=tmp_path/'bundle';root.mkdir();body=b'{"timestamp":"2026-09-15T01:02:03Z","request_id":"abc","method":"GET","url":"/hello","status":200,"unknown":{"keep":true}}\n'
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as z:z.writestr('uploads/auto/var/log/nginx/access.json',body)
    body=output.getvalue();path=root/'triage.zip';path.write_bytes(body)
    manifest={'schema_version':'1.1','case_id':'CASE-local','integrity':'PARTIAL' if partial else 'PASS',
        'target':{'account_id':'111111111111','region':'ap-northeast-2','instance_id':'i-0123456789abcdef0'},
        'jobs':[{'key':'cases/CASE-local/triage.zip','sha256':hashlib.sha256(body).hexdigest(),'size_bytes':len(body),'status':'verified',
        'destination':{'bucket':'final','key':'cases/CASE-local/triage.zip','version_id':'v1'}}]}
    (root/'manifest.json').write_text(json.dumps(manifest));return root,path

def test_cloud_round_trip_timeline_raw_and_idempotent(tmp_path):
    root,_=bundle(tmp_path);db=tmp_path/'case.sqlite'
    result=ingest_cloud(root,db);assert result['records']==1
    assert ingest_cloud(root,db)['records']==0
    store=Store(db,readonly=True)
    try:
        row=store.db.execute('SELECT raw_json FROM records').fetchone()
        assert json.loads(row[0])['unknown']=={'keep':True}
        assert store.db.execute("SELECT count(*) FROM edges WHERE basis='shared_request_id'").fetchone()[0]==1
    finally:store.close()
    timeline=TimelineIndex(db);assert timeline.items[0]['lane']=='cloud'
    assert timeline.items[0]['time_kind']=='event_recorded'

def test_tampered_bundle_never_creates_case(tmp_path):
    root,path=bundle(tmp_path);path.write_bytes(b'tampered');db=tmp_path/'case.sqlite'
    with pytest.raises(ValueError,match='mismatch'):ingest_cloud(root,db)
    assert not db.exists()

def test_partial_requires_explicit_flag(tmp_path):
    root,_=bundle(tmp_path,True);db=tmp_path/'case.sqlite'
    with pytest.raises(ValueError,match='partial'):ingest_cloud(root,db)
    assert ingest_cloud(root,db,True)['integrity']=='PARTIAL'

def test_modsecurity_nested_request_id_without_invented_timezone(tmp_path):
    root,path=bundle(tmp_path)
    with zipfile.ZipFile(path,'a') as z:
        z.writestr('uploads/auto/var/log/modsecurity/audit.json',json.dumps({'transaction':{'unique_id':'abc','time_stamp':'Tue Sep 15 06:25:09 2026','messages':[]}}))
    manifest=json.loads((root/'manifest.json').read_text());job=manifest['jobs'][0]
    job.update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),size_bytes=path.stat().st_size)
    (root/'manifest.json').write_text(json.dumps(manifest));db=tmp_path/'case.sqlite';ingest_cloud(root,db)
    store=Store(db,readonly=True)
    try:
        assert store.db.execute("SELECT count(*) FROM edges WHERE basis='shared_request_id'").fetchone()[0]==2
        assert store.db.execute("SELECT count(DISTINCT target) FROM edges WHERE basis='shared_request_id'").fetchone()[0]==1
        assert store.db.execute("SELECT time_utc FROM records WHERE kind='waf_event'").fetchone()[0] is None
    finally:store.close()
