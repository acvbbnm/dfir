"""Inspect/start/stop exactly the EC2/RDS resources in saved lab outputs.

Default prints a plan after live identity/tag checks. --execute performs that plan.
Infrastructure idle is separate: endpoints/NAT removal does not stop compute.
"""
import argparse
import json
from pathlib import Path
import re
import boto3

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--outputs',type=Path,required=True)
    p.add_argument('--profile',required=True);p.add_argument('--account',required=True);p.add_argument('--region',default='ap-northeast-2')
    p.add_argument('--project',default='ea');p.add_argument('--action',choices=['status','start','stop'],default='status')
    p.add_argument('--execute',action='store_true');a=p.parse_args()
    outputs=json.loads(a.outputs.read_text());value=lambda key:outputs[key]['value']
    roles=['web','app','soc']
    if outputs.get('test_instance_id',{}).get('value'):roles.append('test')
    ids=[value(role+'_instance_id') for role in roles]
    if any(not re.fullmatch(r'i-[a-f0-9]{8,17}',i) for i in ids):raise ValueError('Invalid instance ID')
    session=boto3.Session(profile_name=a.profile,region_name=a.region)
    if session.client('sts').get_caller_identity()['Account']!=a.account:raise ValueError('Wrong AWS account')
    ec2=session.client('ec2');rds=session.client('rds');dbid=value('rds_identifier')
    reservations=ec2.describe_instances(InstanceIds=ids)['Reservations'];states={}
    for reservation in reservations:
        for item in reservation['Instances']:
            tags={t['Key']:t['Value'] for t in item.get('Tags',[])}
            if tags.get('Name') not in [a.project+'-'+role for role in roles]:raise ValueError('Foreign instance')
            states[item['InstanceId']]=item['State']['Name']
    if set(states)!=set(ids):raise ValueError('Missing instance inventory')
    db=rds.describe_db_instances(DBInstanceIdentifier=dbid)['DBInstances'][0]
    if db['DBInstanceIdentifier']!=a.project+'-mysql':raise ValueError('Foreign database')
    plan={'action':a.action,'account':a.account,'region':a.region,'instances':states,'database':{'id':dbid,'status':db['DBInstanceStatus']}}
    print(json.dumps(plan,indent=2))
    if not a.execute or a.action=='status':return
    if a.action=='stop':
        active=[i for i,s in states.items() if s=='running']
        if active:ec2.stop_instances(InstanceIds=active)
        if db['DBInstanceStatus']=='available':rds.stop_db_instance(DBInstanceIdentifier=dbid)
    else:
        stopped=[i for i,s in states.items() if s=='stopped']
        if stopped:ec2.start_instances(InstanceIds=stopped)
        if db['DBInstanceStatus']=='stopped':rds.start_db_instance(DBInstanceIdentifier=dbid)
    print('Requested state changes; poll status until transitions finish. ALB/storage charges remain.')

if __name__=='__main__':main()
