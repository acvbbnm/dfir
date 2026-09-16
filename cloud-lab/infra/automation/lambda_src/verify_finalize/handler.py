"""Bounded, streaming finalization; incomplete collection never becomes READY."""
import json
import os
from datetime import datetime, timezone
import boto3
from common.evidence import copy_verified

REGION = os.environ.get('REGION','ap-northeast-2')
STAGING_BUCKET = os.environ.get('STAGING_BUCKET','')
FINAL_BUCKET = os.environ.get('FINAL_BUCKET','')
CASES_TABLE = os.environ.get('CASES_TABLE','ea-cases')

def lambda_handler(event, context):
    case_id = event['case_id']
    if not __import__('re').fullmatch(r'CASE-[A-Za-z0-9_-]{1,59}',case_id):
        raise ValueError('Invalid case ID')
    s3 = boto3.client('s3',region_name=REGION)
    results = event.get('collection_results',[])
    missing, jobs = [], []
    for stage in ('metadata_error','collection_error'):
        if event.get(stage):
            missing.append({'key':stage,'error':str(event[stage])})
    if not results:
        missing.append({'key':'collection','error':'No collection completion results'})
    for i,result in enumerate(results):
        if result.get('error') or result.get('errors') or (result.get('status') not in ('SUCCESS','Success') and not result.get('skipped')):
            missing.append({'key':f'collection/{i}','error':json.dumps(result,default=str)})
    if event.get('metadata',{}).get('errors'):
        missing.append({'key':'metadata','error':str(event['metadata']['errors'])})
    maximum = int(os.environ.get('VERIFY_MAX_BYTES','67108864'))
    objects, total = 0, 0
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=STAGING_BUCKET,Prefix=f'cases/{case_id}/'):
        for obj in page.get('Contents',[]):
            key = obj['Key']
            objects += 1
            total += obj['Size']
            try:
                if total > 256*1024*1024:
                    raise ValueError('Case exceeds current verification budget; preserve staging and split the collection scope before retry')
                if context is not None and context.get_remaining_time_in_millis() < 15000:
                    raise ValueError('Verification time budget exhausted')
                verified=copy_verified(s3,STAGING_BUCKET,FINAL_BUCKET,key,
                    os.environ['EVIDENCE_KMS_KEY_ARN'],case_id,maximum)
                producer=next((r for r in results if r.get('output_key')==key),None)
                if producer:
                    if producer.get('producer_sha256')!=verified['sha256'] or producer.get('version_id')!=verified['source']['version_id']:
                        raise ValueError('Host-produced digest/version does not match evidence')
                    verified['producer_sha256']=producer['producer_sha256']
                jobs.append(verified)
            except Exception as exc:
                missing.append({'key':key,'error':str(exc)})
    integrity = 'FAIL' if not jobs else 'PARTIAL' if missing else 'PASS'
    manifest = {'schema_version':'1.1','case_id':case_id,
        'finalized_at':datetime.now(timezone.utc).isoformat(), 'integrity':integrity,
        'collection_profile':'linux-triage-v1/aws-case-v1','verifier_version':'1.1',
        'target':event.get('target',{}),'trigger':event.get('trigger',{}),
        'total_objects':objects,'verified_objects':len(jobs),'missing_objects':len(missing),
        'total_size_bytes':total,'jobs':jobs,'missing':missing,'collection_results':results}
    key = f'cases/{case_id}/manifest.json'
    written = s3.put_object(Bucket=FINAL_BUCKET,Key=key,
        Body=json.dumps(manifest,ensure_ascii=False,default=str).encode(),ContentType='application/json',
        ServerSideEncryption='aws:kms',SSEKMSKeyId=os.environ['EVIDENCE_KMS_KEY_ARN'])
    boto3.resource('dynamodb',region_name=REGION).Table(CASES_TABLE).update_item(
        Key={'case_id':case_id},UpdateExpression='SET #s=:s, manifest_key=:k, manifest_version=:v, updated_at=:t',
        ExpressionAttributeNames={'#s':'status'},ExpressionAttributeValues={
            ':s':{'PASS':'READY','PARTIAL':'PARTIAL','FAIL':'FAILED'}[integrity],
            ':k':key,':v':written.get('VersionId',''),':t':manifest['finalized_at']})
    return {'integrity':integrity,'manifest_key':key,'missing':missing}
