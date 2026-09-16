"""Create a least-privilege ES API key and local SOC reader configuration."""
import json
import os
from pathlib import Path
import requests

def sources(project,workload,security,region,extra_regions=()):
    common={'region':region,'account_id':workload}
    return {'sources':[
        *[{'region':event_region,'account_id':account,'transport':'s3','kind':'cloudtrail',
           'bucket':f'{project}-cloudtrail-{security}',
           'prefix':f'AWSLogs/{account}/CloudTrail/{event_region}/'+'{date}/',
           'role_arn':f'arn:aws:iam::{security}:role/{project}-central-log-reader'}
          for account in dict.fromkeys((workload,security))
          for event_region in dict.fromkeys((region,'us-east-1',*extra_regions))],
        {**common,'transport':'s3','kind':'alb','bucket':f'{project}-alb-logs-{workload}',
         'prefix':f'alb/AWSLogs/{workload}/elasticloadbalancing/{region}/'+'{date}/'},
        {**common,'transport':'s3','kind':'vpc-flow','bucket':f'{project}-flow-logs-{workload}',
         'prefix':f'AWSLogs/{workload}/vpcflowlogs/{region}/'+'{date}/'},
        *[{**common,'transport':'cloudwatch','kind':'rds-'+kind,'log_group':f'/aws/rds/instance/{project}-mysql/{kind}'} for kind in ('error','slowquery')],
        {**common,'transport':'cloudwatch','kind':'resolver-dns','log_group':f'/{project}/resolver'}]}

def main():
    project=os.environ['PROJECT'];workload=os.environ['WORKLOAD_ACCOUNT_ID'];security=os.environ['SECURITY_ACCOUNT_ID'];region=os.environ['AWS_REGION']
    target=Path('/etc/ea-collector');target.mkdir(mode=0o750,exist_ok=True)
    key_file=target/'es-api-key'
    if not key_file.exists():
        response=requests.post('https://localhost:9200/_security/api_key',
            auth=('elastic',Path('/root/ea-credentials/elastic').read_text().strip()),
            verify='/etc/elasticsearch/ea-certs/ca/ca.crt',timeout=30,
            json={'name':'ea-cloud-collectors','expiration':'7d','role_descriptors':{'ea':{'cluster':[],
                'indices':[{'names':['.alerts-security.alerts-*'],'privileges':['read','view_index_metadata'],'allow_restricted_indices':True},
                           {'names':['logs-ea.aws-*'],'privileges':['create_doc','auto_configure']}]}}})
        response.raise_for_status();key_file.write_text(response.json()['encoded']);key_file.chmod(0o600)
    values={'ES_URL':'https://localhost:9200','ES_API_KEY':key_file.read_text().strip(),'ES_CA':'/etc/ea-collector/es-ca.pem',
        'EVENT_BUS':f'arn:aws:events:{region}:{security}:event-bus/{project}-security-events','REGION':region,
        'SECURITY_ACCOUNT_ID':security,'CURSOR_FILE':'/var/lib/ea-collector/alerts.json','KIBANA_SPACE':'default'}
    (target/'env').write_text(''.join(k+'='+json.dumps(v)+'\n' for k,v in values.items()));(target/'env').chmod(0o640)
    (target/'cloud-sources.json').write_text(json.dumps(sources(project,workload,security,region,tuple(filter(None,os.environ.get('AUDIT_EXTRA_REGIONS','').split(',')))),indent=2))
    print('Collector configuration created; API key expires in 7 days, rotate explicitly before longer sessions')

if __name__=='__main__':main()
