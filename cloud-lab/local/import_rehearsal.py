"""Import an actual local triage ZIP without representing it as AWS evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from dfir_graph.cloud import ingest_cloud
from dfir_graph.store import Store
from dfir_graph.timeline import TimelineIndex

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('zip',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    body=a.zip.read_bytes();digest=hashlib.sha256(body).hexdigest();case='CASE-LOCAL-WAF'
    shutil.copyfile(a.zip,a.output/'triage.zip')
    manifest={'schema_version':'1.1','case_id':case,'integrity':'PASS','origin':'LOCAL_DOCKER_REHEARSAL_NOT_AWS',
        'target':{'account_id':'local-docker','region':'local','instance_id':'ea-ready-waf-v2'},
        'jobs':[{'key':f'cases/{case}/triage.zip','sha256':digest,'size_bytes':len(body),'status':'verified',
            'source':{'transport':'local-docker','container':'ea-ready-waf-v2','path':'/tmp/triage.zip'},
            'destination':{'bucket':'LOCAL_FIXTURE_NOT_S3','key':f'cases/{case}/triage.zip','version_id':'local-sha256-'+digest}}]}
    (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    database=a.output/'atlas.sqlite';result=ingest_cloud(a.output,database)
    repeated=ingest_cloud(a.output,database);assert repeated['records']==0
    store=Store(database,readonly=True)
    try:
        correlations=store.db.execute("SELECT target,count(*) FROM edges WHERE basis='shared_request_id' GROUP BY target HAVING count(*)>1").fetchall()
        assert len(correlations)>=2,'WAF/access-log shared requests missing'
        blocked=store.db.execute("SELECT raw_json FROM records WHERE kind='web_request'").fetchall()
        assert any(json.loads(row[0]).get('status')==403 for row in blocked),'Real WAF block record missing'
        with zipfile.ZipFile(a.zip) as archive:
            original=archive.read('uploads/auto/var/log/modsecurity/audit.json')
        source=store.db.execute("SELECT sha256 FROM sources WHERE relative_path LIKE '%modsecurity/audit.json'").fetchone()
        assert source[0]==hashlib.sha256(original).hexdigest(),'Original member digest mismatch'
        result.update(shared_requests=len(correlations),timeline_observations=len(TimelineIndex(database).items),
            zip_sha256=digest,scope='local Docker evidence only; no AWS object versions',repeat_records=repeated['records'])
    finally:store.close()
    (a.output/'import-report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
