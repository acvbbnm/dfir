"""Convert an executed HTTP receipt and explicit expectations to an unreviewed answer.
No network calls. A response status does not establish compromise or detection.
"""
import argparse
from datetime import datetime
import re
import hashlib
import json
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker

ROOT=Path(__file__).resolve().parents[1]

def answer_validator():
    checker=FormatChecker()
    @checker.checks('date-time',raises=(ValueError,TypeError))
    def strict_datetime(value):
        if not isinstance(value,str):return True
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})',value):return False
        return datetime.fromisoformat(value.replace('Z','+00:00')).tzinfo is not None
    schema=json.loads((ROOT/'scenarios/schemas/answer.schema.json').read_text(encoding='utf-8'))
    return Draft202012Validator(schema,format_checker=checker)

def convert(receipt,expectations,receipt_sha256):
    if receipt.get('executed') is not True or not receipt.get('executed_at'):
        raise ValueError('An offline plan is not an executed answer')
    results=receipt.get('results',[])
    if not results:raise ValueError('No completed HTTP observations')
    expected=expectations.get('expected_results',[])
    if len(expected)!=len(receipt['actions']):raise ValueError('Specify expected_results for every planned action')
    for value in expected:
        if value not in ('success','blocked','partial','observation'):raise ValueError('Invalid expected result')
    evidence=expectations.get('expected_evidence')
    if not isinstance(evidence,dict) or not evidence:raise ValueError('Specify expected_evidence before assessing a run')
    policies=expectations.get('policy_versions')
    if not isinstance(policies,dict) or not policies:raise ValueError('Specify observed policy_versions')
    if len(results)>len(receipt['actions']):raise ValueError('Receipt action count mismatch')
    actions=[]
    for n,row in enumerate(results):
        method,path,_=receipt['actions'][n]
        if (row['method'],row['path'])!=(method,path):raise ValueError('Receipt action order mismatch')
        actions.append({'step':n+1,'command':method+' '+path,'expected_result':expected[n],
            'actual_result':f"HTTP {row['status']}; effect and detection unreviewed",
            'timestamp':row['timestamp'],'observation':row})
    answer={'schema_version':'1.1','record_type':'answer','assessment_status':'unreviewed',
        'scenario_id':receipt['scenario_id'],'run_id':receipt['run_id'],'executed_at':receipt['executed_at'],
        'targets':[{'resource_type':'http_origin','resource_id':receipt['target']}],
        'actions':actions,'expected_evidence':evidence,'policy_versions':policies,
        'detection_rules':expectations.get('detection_rules',[]),'receipt_sha256':receipt_sha256,
        'execution_error':receipt.get('error'),'execution_complete':not receipt.get('error') and len(results)==len(receipt['actions']),
        'coverage':{source:{stage:'not_evaluated' for stage in ('observed','parsed','detected','blocked','collected')} for source in evidence}}
    answer_validator().validate(answer)
    return answer

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('receipt','expectations','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();raw=a.receipt.read_bytes()
    answer=convert(json.loads(raw.decode('utf-8-sig')),json.loads(a.expectations.read_text(encoding='utf-8-sig')),hashlib.sha256(raw).hexdigest())
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x',encoding='utf-8',newline='\n') as stream:json.dump(answer,stream,ensure_ascii=False,indent=2)
    print('Unreviewed answer saved; receipt preserved; no AWS calls')

if __name__=='__main__':main()
