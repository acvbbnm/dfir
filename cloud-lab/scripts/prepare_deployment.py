"""Render private deployment inputs offline. No AWS calls, plan or apply."""
import argparse
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
EXAMPLE={'security_account_id':'','workload_account_id':'','region':'ap-northeast-2','project':'ea',
         'budget_notification_email':'','ami_id':'','security_profile':'ea-security','workload_profile':'ea-workload',
         'security_deploy_principal_arn':'','budget_limit_usd':300,'enable_test_runner':False,
         'note':'Fill identifiers only; never put access keys, passwords or session tokens here.'}

def config_checks(c):
    for key in ('security_account_id','workload_account_id'):
        if not re.fullmatch(r'[0-9]{12}',c.get(key,'')):raise ValueError('Provide '+key)
    if c['security_account_id']==c['workload_account_id']:raise ValueError('Two distinct accounts are required')
    if c.get('region')!='ap-northeast-2' or c.get('project')!='ea':
        raise ValueError('This reviewed baseline is ea in ap-northeast-2; other regions/names require design review')
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',c.get('budget_notification_email','')):raise ValueError('Provide notification email')
    principal=c.get('security_deploy_principal_arn','')
    if not re.fullmatch(r'arn:aws:iam::'+c['security_account_id']+r':role/[A-Za-z0-9_+=,.@/-]+',principal):
        raise ValueError('Provide the exact Security deployment IAM role ARN (not STS session ARN or account root)')
    for field in ('security_profile','workload_profile'):
        if not re.fullmatch(r'[A-Za-z0-9_-]+',c.get(field,'')):raise ValueError('Invalid '+field)
    if c['security_profile']==c['workload_profile']:raise ValueError('Use distinct named profiles')
    if not isinstance(c.get('scenario_lambda_arns',[]),list):raise ValueError('scenario_lambda_arns must be a list')
    for arn in c.get('scenario_lambda_arns',[]):
        if not isinstance(arn,str) or not re.fullmatch(r'arn:aws:lambda:[a-z0-9-]+:'+c['workload_account_id']+r':function:ea-scenario-[A-Za-z0-9_-]+',arn):
            raise ValueError('Use exact Workload ea-scenario-* Lambda ARNs')
    if len(c.get('scenario_lambda_arns',[]))>5:raise ValueError('At most five scenario Lambda targets')
    regions=c.get('audit_extra_regions',[])
    if not isinstance(regions,list) or len(regions)>3 or any(not isinstance(r,str) or not re.fullmatch(r'[a-z]{2}(?:-[a-z]+)+-\d',r) for r in regions):
        raise ValueError('Provide at most three explicit audit_extra_regions')
    limit=c.get('budget_limit_usd',300)
    if isinstance(limit,bool) or not isinstance(limit,(int,float)) or not 0<limit<=300:raise ValueError('Budget must be >0 and <=300 USD')
    if type(c.get('enable_test_runner',False)) is not bool:raise ValueError('enable_test_runner must be boolean')

def render(c,foundation=None):
    config_checks(c)
    common={k:c[k] for k in ('security_account_id','workload_account_id','region','project')}
    limit=c.get('budget_limit_usd',300)
    files={'foundation.tfvars.json':{**common,'budget_notification_email':c['budget_notification_email'],
            'budget_limit_usd':limit,'budget_warning_usd':limit*2/3,'budget_critical_usd':limit*5/6,'scenario_lambda_arns':c.get('scenario_lambda_arns',[])},
           'workload-deploy-trust.json':{'Version':'2012-10-17','Statement':[{'Effect':'Allow',
            'Principal':{'AWS':c['security_deploy_principal_arn']},'Action':'sts:AssumeRole'}]}}
    for stage in ('foundation','lab','automation'):
        files[stage+'.backend.hcl']='\n'.join([
            f'bucket = "ea-tofu-state-{c["security_account_id"]}"',f'key = "{stage}/terraform.tfstate"',
            'region = "ap-northeast-2"','encrypt = true','dynamodb_table = "ea-tofu-lock"',
            f'profile = "{c["security_profile"]}"',''])
    if foundation is None:return files
    if not re.fullmatch(r'ami-[a-f0-9]{8,17}',c.get('ami_id','')):raise ValueError('Provide reviewed Ubuntu 24.04 AMI ID before lab inputs')
    get=lambda name:foundation[name]['value']
    security=c['security_account_id'];workload=c['workload_account_id']
    for name,account in (('kms_workload_ebs_arn',workload),('kms_evidence_s3_arn',security)):
        if not str(get(name)).startswith(f'arn:aws:kms:ap-northeast-2:{account}:key/'):raise ValueError('Unexpected account/region in '+name)
    for name,expected in [('s3_alb_logs_bucket',f'ea-alb-logs-{workload}'),
            ('s3_evidence_staging_bucket',f'ea-evidence-staging-{security}'),
            ('s3_evidence_final_bucket',f'ea-evidence-final-{security}')]:
        if get(name)!=expected:raise ValueError('Foreign foundation output: '+name)
    for stage in ('staging','final'):
        if get('s3_evidence_'+stage+'_arn')!='arn:aws:s3:::'+get('s3_evidence_'+stage+'_bucket'):
            raise ValueError('Evidence ARN/bucket mismatch')
    lock=json.loads((ROOT/'artifacts.lock.json').read_text(encoding='utf-8'))
    wp=lock['artifacts']['wordpress']
    files['lab.tfvars.json']={**common,'audit_extra_regions':c.get('audit_extra_regions',[]),'ami_id':c['ami_id'],'operation_mode':'setup','enable_aws_waf':False,
        'waf_mode':'DetectionOnly','enable_test_runner':c.get('enable_test_runner',False),
        'wordpress_version':wp['version'],'wordpress_sha256':wp['sha256'],'elastic_version':lock['elastic']['version'],
        'kms_workload_ebs_arn':get('kms_workload_ebs_arn'),'s3_alb_logs_bucket':get('s3_alb_logs_bucket'),
        'evidence_bucket':get('s3_evidence_staging_bucket'),'evidence_kms_key_arn':get('kms_evidence_s3_arn')}
    files['automation.tfvars.json']={**common,'audit_extra_regions':c.get('audit_extra_regions',[]),'collection_enabled':False,**{key:get(key) for key in (
        'kms_evidence_s3_arn','s3_evidence_staging_arn','s3_evidence_staging_bucket','s3_evidence_final_arn','s3_evidence_final_bucket')}}
    return files

def write_new(folder,files):
    folder.mkdir(parents=True,exist_ok=True)
    if any((folder/name).exists() for name in files):raise ValueError('Use a new directory; existing inputs will not be overwritten')
    for name,value in files.items():
        path=folder/name;path.write_text(value if isinstance(value,str) else json.dumps(value,indent=2)+'\n',encoding='utf-8')
        path.chmod(0o600)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--example',action='store_true');p.add_argument('--config',type=Path);p.add_argument('--foundation-outputs',type=Path)
    a=p.parse_args()
    if a.example:files={'deployment.example.json':EXAMPLE}
    else:
        if not a.config:p.error('--config is required')
        c=json.loads(a.config.read_text(encoding='utf-8-sig'))
        foundation=json.loads(a.foundation_outputs.read_text(encoding='utf-8-sig')) if a.foundation_outputs else None
        files=render(c,foundation)
    write_new(a.output,files)
    print(json.dumps({'files':sorted(files),'output':str(a.output),'aws_calls':0,'applied':False}))

if __name__=='__main__':main()
