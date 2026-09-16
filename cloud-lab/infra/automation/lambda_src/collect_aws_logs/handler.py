"""Preserve versioned originals across audit accounts/regions plus a bounded lookup derivative."""
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
import boto3

REGION=os.environ.get('REGION','ap-northeast-2')
STAGING_BUCKET=os.environ.get('STAGING_BUCKET','')

def audit_scope():
    accounts=list(dict.fromkeys(filter(None,(os.environ['WORKLOAD_ACCOUNT_ID'],os.environ.get('SECURITY_ACCOUNT_ID')))))
    regions=list(dict.fromkeys((REGION,'us-east-1',*filter(None,os.environ.get('AUDIT_EXTRA_REGIONS','').split(',')))))
    if len(regions)>5 or any(not re.fullmatch(r'[a-z]{2}(?:-[a-z]+)+-\d',r) for r in regions):raise ValueError('Invalid bounded audit region scope')
    if any(not re.fullmatch(r'\d{12}',a) for a in accounts):raise ValueError('Invalid audit account')
    return accounts,regions

def capture_originals(s3,case,start,end,context=None):
    bucket=os.environ['CLOUDTRAIL_BUCKET'];accounts,regions=audit_scope()
    objects=[];errors=[];total=0;day=start.date()
    while day<=end.date():
        for account in accounts:
            for region in regions:
                for category in ('CloudTrail','CloudTrail-Digest'):
                    prefix=f'AWSLogs/{account}/{category}/{region}/{day:%Y/%m/%d}/'
                    try:
                        for page in s3.get_paginator('list_objects_v2').paginate(Bucket=bucket,Prefix=prefix):
                            for item in page.get('Contents',[]):
                                total+=item['Size']
                                if len(objects)>=128 or total>128*1024*1024 or item['Size']>64*1024*1024:
                                    return objects,errors+['Original log capture byte/object budget exceeded']
                                if context and context.get_remaining_time_in_millis()<30000:
                                    return objects,errors+['Original log capture time budget exhausted']
                                key=item['Key']
                                try:
                                    head=s3.head_object(Bucket=bucket,Key=key);version=head.get('VersionId')
                                    if not version or version=='null':raise ValueError('Original log has no immutable version')
                                    suffix=hashlib.sha256((bucket+'/'+key+'#'+version).encode()).hexdigest()[:24]
                                    destination=f'cases/{case}/aws-logs/original/{suffix}/{key.rsplit("/",1)[-1]}'
                                    copy=s3.copy_object(Bucket=STAGING_BUCKET,Key=destination,
                                        CopySource={'Bucket':bucket,'Key':key,'VersionId':version},
                                        ServerSideEncryption='aws:kms',SSEKMSKeyId=os.environ['EVIDENCE_KMS_KEY_ARN'],
                                        MetadataDirective='REPLACE',Metadata={'source-kind':'cloudtrail-original' if category=='CloudTrail' else 'cloudtrail-digest',
                                            'original-bucket':bucket,'original-key':key,'original-version':version})
                                    if not copy.get('VersionId') or copy['VersionId']=='null':raise ValueError('Staging copy not versioned')
                                    objects.append({'source':{'bucket':bucket,'key':key,'version_id':version},
                                        'staging':{'bucket':STAGING_BUCKET,'key':destination,'version_id':copy['VersionId']},
                                        'account_id':account,'region':region,'category':category,'size_bytes':head['ContentLength']})
                                except Exception as exc:errors.append({'key':key,'error':str(exc)})
                    except Exception as exc:errors.append({'prefix':prefix,'error':str(exc)})
        day+=timedelta(days=1)
    if not any(obj['category']=='CloudTrail' for obj in objects):errors.append('No original CloudTrail log delivered for requested dates')
    return objects,errors

def lookup_derivative(start,end,context=None):
    accounts,regions=audit_scope();records=[];errors=[];seen=set()
    for account in accounts:
        try:
            auth={}
            if account==os.environ['WORKLOAD_ACCOUNT_ID']:
                creds=boto3.client('sts',region_name=REGION).assume_role(
                    RoleArn=f"arn:aws:iam::{account}:role/{os.environ.get('PROJECT','ea')}-collection-target",
                    RoleSessionName='ea-log-lookup',DurationSeconds=900)['Credentials']
                auth=dict(aws_access_key_id=creds['AccessKeyId'],aws_secret_access_key=creds['SecretAccessKey'],aws_session_token=creds['SessionToken'])
            for region in regions:
                try:
                    ct=boto3.client('cloudtrail',region_name=region,**auth)
                    # Do not filter by EC2 ID: IAM/STS operations often have no instance resource.
                    for page in ct.get_paginator('lookup_events').paginate(StartTime=start,EndTime=end,MaxResults=50):
                        for row in page.get('Events',[]):
                            identity=(account,region,row.get('EventId',json.dumps(row,default=str,sort_keys=True)))
                            if identity not in seen:
                                seen.add(identity);records.append({'account_id':account,'lookup_region':region,'event':row})
                            if len(records)>=1000:return records,errors+['Lookup derivative reached 1000-event limit']
                        if context and context.get_remaining_time_in_millis()<30000:return records,errors+['Lookup time budget exhausted']
                except Exception as exc:errors.append(f'Lookup {account}/{region}: {exc}')
        except Exception as exc:errors.append(f'Lookup role {account}: {exc}')
    return records,errors

def lambda_handler(event,context):
    case=event['case_id'];detected=event.get('trigger',{}).get('detected_at')
    if not detected:raise ValueError('Incident event time is required')
    center=datetime.fromisoformat(detected.replace('Z','+00:00'))
    if center.tzinfo is None:raise ValueError('Incident time requires a timezone')
    center=center.astimezone(timezone.utc)
    window=int(event.get('time_window_minutes',15))
    if not 0<=window<=60:raise ValueError('Time window outside bounded profile')
    start=center-timedelta(minutes=window);end=center+timedelta(minutes=window)
    s3=boto3.client('s3',region_name=REGION)
    objects,errors=capture_originals(s3,case,start,end,context)
    now=datetime.now(timezone.utc)
    if end+timedelta(minutes=30)>now:errors.append('Window or log delivery grace period still open; reconcile after window end + 30 minutes')
    records=[]
    if start<=now:
        records,lookup_errors=lookup_derivative(start,min(end,now),context);errors.extend(lookup_errors)
    else:errors.append('Incident window has not started')
    def write(name,value,kind):
        return s3.put_object(Bucket=STAGING_BUCKET,Key=f'cases/{case}/aws-logs/{name}',
            Body=json.dumps(value,ensure_ascii=False,default=str).encode(),ContentType='application/json',
            ServerSideEncryption='aws:kms',SSEKMSKeyId=os.environ['EVIDENCE_KMS_KEY_ARN'],Metadata={'source-kind':kind})
    if records:write('lookup-derivative.json',records,'cloudtrail-lookup-derivative')
    accounts,regions=audit_scope()
    metadata={'case_id':case,'collected_at':now.isoformat(),'time_window':{'start':start.isoformat(),'end':end.isoformat()},
        'coverage':{'accounts':accounts,'regions':regions,'originals':'Whole date prefixes; only events configured on the source trails',
                    'lookup':'Management only; bounded by event/time limits; not an absence claim'},
        'digest_signature_validated':False,'originals':objects,'lookup_count':len(records),'errors':errors}
    write('collection-metadata.json',metadata,'collection-metadata')
    return {'status':'PARTIAL' if errors else 'SUCCESS','original_objects':len(objects),'lookup_events':len(records),
        'errors':errors,'coverage':metadata['coverage']}
