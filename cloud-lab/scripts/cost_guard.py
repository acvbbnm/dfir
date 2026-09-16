"""Read cumulative project-period account costs; monthly alerts are not a spend cap."""
import argparse
from datetime import date,timedelta
from decimal import Decimal
import json
import boto3

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--start-date',required=True)
    p.add_argument('--workload-profile',required=True);p.add_argument('--security-profile',required=True)
    p.add_argument('--limit',type=Decimal,default=Decimal('300'));a=p.parse_args()
    start=date.fromisoformat(a.start_date);end=date.today()+timedelta(days=1)
    if start>end:raise ValueError('Start date is in the future')
    seen=set();reports=[];total=Decimal('0')
    for profile in (a.workload_profile,a.security_profile):
        session=boto3.Session(profile_name=profile,region_name='us-east-1')
        account=session.client('sts').get_caller_identity()['Account']
        if account in seen:raise ValueError('Profiles point to the same account; review intended topology')
        seen.add(account);amount=Decimal('0');estimated=False
        args={'TimePeriod':{'Start':str(start),'End':str(end)},'Granularity':'DAILY','Metrics':['UnblendedCost'],
            'Filter':{'And':[{'Dimensions':{'Key':'LINKED_ACCOUNT','Values':[account]}},
                {'Not':{'Dimensions':{'Key':'RECORD_TYPE','Values':['Credit','Refund']}}}]}}
        client=session.client('ce')
        while True:
            response=client.get_cost_and_usage(**args)
            for day in response['ResultsByTime']:
                cost=day['Total']['UnblendedCost']
                if cost['Unit']!='USD':raise ValueError('Unexpected billing currency')
                amount+=Decimal(cost['Amount']);estimated|=day.get('Estimated',False)
            if not response.get('NextPageToken'):break
            args['NextPageToken']=response['NextPageToken']
        total+=amount;reports.append({'account':account,'usage_before_credit_usd':str(amount),'estimated':estimated})
    print(json.dumps({'start':str(start),'accounts':reports,'total_usd':str(total),'remaining_usd':str(a.limit-total),
        'status':'STOP_REVIEW' if total>=a.limit*Decimal('0.8') else 'BELOW_WARNING',
        'note':'Billing is delayed. Includes other workloads in these accounts; does not automatically stop resources.'},indent=2))
    return 2 if total>=a.limit*Decimal('0.8') else 0

if __name__=='__main__':raise SystemExit(main())
