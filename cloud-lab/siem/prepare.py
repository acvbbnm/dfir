"""Render a reviewable Elastic/Fleet API plan; apply only to an explicit HTTPS endpoint.

Use on the SOC host after TLS installation. The default only writes JSON files.
Tokens/passwords are read from files and are never written into the plan.
"""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse
import requests

PACKAGES={'endpoint':'8.19.3','filestream':'1.2.0','fleet_server':'1.6.1'}
LOGS={'web':{'nginx':['/var/log/nginx/access.json'],'modsecurity':['/var/log/modsecurity/audit.json'],
             'suricata':['/var/log/suricata/eve.json'],'auditd':['/var/log/audit/audit.log'],'auth':['/var/log/auth.log']},
      'app':{'wordpress':['/var/log/wp-audit/*.json'],'apache':['/var/log/apache2/*access.log','/var/log/apache2/*error.log'],
             'auditd':['/var/log/audit/audit.log'],'auth':['/var/log/auth.log']}}

def build(soc,ca):
    if not soc.startswith('https://') or urlparse(soc).path not in ('','/'):
        raise ValueError('SOC must be an HTTPS origin without path')
    host=urlparse(soc).hostname
    plan=[]
    def add(service,method,path,body):plan.append(dict(service=service,method=method,path=path,body=body))
    add('es','PUT','/_ilm/policy/ea-lab',{'policy':{'phases':{'hot':{'actions':{'rollover':{'max_age':'1d','max_primary_shard_size':'1gb'}}},'delete':{'min_age':'7d','actions':{'delete':{}}}}}})
    add('es','PUT','/_component_template/ea-lab',{'template':{'settings':{'index.lifecycle.name':'ea-lab','index.number_of_shards':1,'index.number_of_replicas':0},'mappings':{'properties':{'event':{'properties':{'original':{'type':'keyword','index':False,'doc_values':False},'dataset':{'type':'keyword'},'provider':{'type':'keyword'},'action':{'type':'keyword'},'outcome':{'type':'keyword'},'kind':{'type':'keyword'},'ingested':{'type':'date'}}},'user':{'properties':{'id':{'type':'keyword'},'name':{'type':'keyword'}}},'cloud':{'properties':{'account':{'properties':{'id':{'type':'keyword'}}},'region':{'type':'keyword'},'provider':{'type':'keyword'}}},'ea':{'properties':{'raw':{'type':'object','enabled':False},'audit':{'properties':{'parameters':{'type':'flattened'},'actor_arn':{'type':'keyword'},'session_issuer':{'type':'keyword'},'event_category':{'type':'keyword'},'source_address':{'type':'keyword'},'resource_arns':{'type':'keyword'},'error_code':{'type':'keyword'},'event_id':{'type':'keyword'}}}}}}}}})
    add('es','PUT','/_index_template/ea-lab',{'index_patterns':['logs-ea.*-*'],'priority':501,'data_stream':{},'composed_of':['ea-lab']})
    add('es','PUT','/_ingest/pipeline/ea-raw-v1',{'description':'Preserve original bytes as message/event.original; derive selected JSON fields only',
        'processors':[{'set':{'field':'event.original','copy_from':'message','override':False}},
          {'json':{'field':'message','target_field':'ea.raw','if':"ctx.message != null && ctx.message.trim().startsWith('{')",'ignore_failure':True}},
          {'script':{'lang':'painless','source':"""if(ctx.ea == null || ctx.ea.raw == null) return;
def r=ctx.ea.raw; if(ctx.event == null) ctx.event=[:];
if(r.timestamp != null) ctx.ea.time_raw=r.timestamp;
if(r.request_id != null) ctx.ea.request_id=r.request_id;
if(r.action != null) ctx.event.action=r.action;
if(r.attempted_user != null) ctx.user=['name':r.attempted_user];
else if(r.user_login != null) ctx.user=['name':r.user_login];
if(r.status != null) { ctx.http=['response':['status_code':r.status]]; }
if(r.alert != null) { ctx.event.kind='alert'; ctx.event.action=r.alert.action; ctx.rule=['id':r.alert.signature_id.toString(),'name':r.alert.signature]; }
if(r.transaction != null) {
  if(r.transaction.unique_id != null) ctx.ea.request_id=r.transaction.unique_id;
  if(r.transaction.messages != null) ctx.ea.waf=['message_count':r.transaction.messages.size()];
}
"""}},
          {'date':{'field':'ea.time_raw','formats':['ISO8601'],'if':'ctx.ea != null && ctx.ea.time_raw != null','ignore_failure':True}}]})
    add('kibana','POST','/api/fleet/setup',{})
    for name,version in PACKAGES.items():add('kibana','POST',f'/api/fleet/epm/packages/{name}/{version}',{})
    add('kibana','PUT','/api/fleet/outputs/fleet-default-output',{'name':'EA verified TLS output','type':'elasticsearch',
        'hosts':[f'https://{host}:9200'],'is_default':True,'is_default_monitoring':True,
        'config_yaml':'ssl.certificate_authorities:\n  - '+json.dumps(ca)+'\n'})
    add('kibana','POST','/api/fleet/fleet_server_hosts',{'id':'ea-fleet-host','name':'EA Fleet Server',
        'host_urls':[f'https://{host}:8220'],'is_default':True})
    for role in ('fleet','web','app'):
        policy='ea-'+role+'-v1'
        add('kibana','POST','/api/fleet/agent_policies',{'id':policy,'name':'EA '+role,'namespace':'ea','monitoring_enabled':['logs','metrics']})
        if role=='fleet':
            add('kibana','POST','/api/fleet/package_policies',{'id':'ea-fleet-server-v1','name':'ea-fleet-server','namespace':'ea','policy_id':policy,
                'package':{'name':'fleet_server','version':PACKAGES['fleet_server']},'inputs':[{'type':'fleet-server','enabled':True,'streams':[]}]})
            continue
        add('kibana','POST','/api/fleet/package_policies',{'id':'ea-'+role+'-defend-v1','name':'ea-'+role+'-defend','namespace':'ea','policy_id':policy,
            'package':{'name':'endpoint','version':PACKAGES['endpoint']},'enabled':True,
            'inputs':[{'type':'ENDPOINT_INTEGRATION_CONFIG','enabled':True,'streams':[],
                'config':{'_config':{'value':{'type':'endpoint','endpointConfig':{'preset':'EDRComplete'}}}}}]})
        for dataset,paths in LOGS[role].items():
            add('kibana','POST','/api/fleet/package_policies',{'id':f'ea-{role}-{dataset}-v1','name':f'ea-{role}-{dataset}',
                'namespace':'ea','policy_id':policy,'package':{'name':'filestream','version':PACKAGES['filestream']},
                'inputs':[{'type':'filestream','policy_template':'filestream','enabled':True,'streams':[{
                    'enabled':True,'data_stream':{'type':'logs','dataset':'filestream.generic'},
                    'vars':{'paths':{'value':paths,'type':'text'},'data_stream.dataset':{'value':'ea.'+dataset,'type':'text'},
                            'pipeline':{'value':'ea-raw-v1','type':'text'},
                            'processors':{'value':'- add_cloud_metadata: {}\n- add_host_metadata: {}','type':'yaml'}}}]}]})
    rules=[('ea-waf-match','WAF rule match','ea.waf.message_count > 0','medium'),
           ('ea-suricata-alert','Suricata alert','event.dataset:ea.suricata and event.kind:alert and rule.id:*','high'),
           ('ea-endpoint-alert','Endpoint alert','event.kind:alert and event.module:endpoint','high')]
    for rid,name,query,severity in rules:
        add('kibana','POST','/api/detection_engine/rules',{'rule_id':rid,'name':name,'description':'Training alert; verify original evidence before conclusions.',
            'risk_score':73 if severity=='high' else 47,'severity':severity,'type':'query','language':'kuery','query':query,
            'index':['logs-ea.*-*','logs-endpoint.alerts-*'],'interval':'1m','from':'now-3m','enabled':True,
            'tags':['evidence-atlas','local-prepared']})
    # Review candidates, not maliciousness verdicts. CloudTrail can arrive late.
    def audit_rule(rid,name,provider,names,threshold=None):
        query='event.dataset:ea.aws AND event.provider:"'+provider+'" AND event.action:('+' OR '.join('"'+n+'"' for n in names)+')'
        body={'rule_id':rid,'name':name,'description':'Sensitive API activity for analyst review; authorized activity can match. Verify original event and permissions.',
            'risk_score':47,'severity':'medium','type':'threshold' if threshold else 'query','language':'lucene',
            'query':query,'index':['logs-ea.aws-*'],'interval':'1m','from':'now-5m',
            'timestamp_override':'event.ingested','timestamp_override_fallback_disabled':False,
            'enabled':True,'tags':['evidence-atlas','scenario-review-v1']}
        if threshold:body['threshold']={'field':['user.id'],'value':threshold}
        add('kibana','POST','/api/detection_engine/rules',body)
    audit_rule('ea-iam-change','IAM policy or identity change','iam.amazonaws.com',
        ['CreateUser','CreateAccessKey','CreateLoginProfile','PutRolePolicy','AttachRolePolicy','SetDefaultPolicyVersion','UpdateAssumeRolePolicy','AddRoleToInstanceProfile'])
    audit_rule('ea-audit-change','CloudTrail logging configuration change','cloudtrail.amazonaws.com',
        ['StopLogging','DeleteTrail','UpdateTrail','PutEventSelectors'])
    audit_rule('ea-rds-share','RDS snapshot attribute change','rds.amazonaws.com',['ModifyDBSnapshotAttribute'])
    audit_rule('ea-ec2-share','EBS or AMI attribute change','ec2.amazonaws.com',['ModifySnapshotAttribute','ModifyImageAttribute'])
    audit_rule('ea-s3-change','Synthetic object or bucket policy change','s3.amazonaws.com',
        ['DeleteObject','DeleteObjects','PutBucketPolicy','DeleteBucketPolicy','PutBucketLifecycle','PutBucketLifecycleConfiguration'])
    audit_rule('ea-s3-read-burst','Object read burst per principal','s3.amazonaws.com',['GetObject'],100)
    audit_rule('ea-secret-read','Secret access review','secretsmanager.amazonaws.com',['GetSecretValue'])
    audit_rule('ea-instance-launch','Instance launch review','ec2.amazonaws.com',['RunInstances'])
    audit_rule('ea-lambda-invoke','Scenario Lambda invocation review','lambda.amazonaws.com',['Invoke'])
    add('kibana','POST','/api/detection_engine/rules',{
        'rule_id':'ea-login-burst','name':'Repeated WordPress login failures per username',
        'description':'Ten failures in five minutes; verify normal load, actor and subsequent login separately.',
        'risk_score':47,'severity':'medium','type':'threshold','language':'kuery',
        'query':'event.dataset:ea.wordpress and event.action:login_failed and user.name:*',
        'threshold':{'field':['user.name'],'value':10},'index':['logs-ea.wordpress-*'],
        'interval':'1m','from':'now-5m','enabled':True,'tags':['evidence-atlas','scenario-review-v1']})
    return plan

def detection_only(base,auth,ca):
    for role in ('web','app'):
        url=base+'/api/fleet/package_policies/ea-'+role+'-defend-v1'
        response=requests.get(url,auth=auth,verify=ca,timeout=30);response.raise_for_status()
        current=response.json()['item']
        payload={key:current[key] for key in ('name','namespace','policy_id','enabled','package','inputs')}
        policy=payload['inputs'][0]['config']['policy']['value']
        policy['global_telemetry_enabled']=False
        for platform in ('linux','windows','mac'):
            for value in policy.get(platform,{}).values():
                if isinstance(value,dict) and value.get('mode')=='prevent':value['mode']='detect'
        response=requests.put(url,json=payload,auth=auth,headers={'kbn-xsrf':'ea'},verify=ca,timeout=60)
        response.raise_for_status()
        verified=requests.get(url,auth=auth,verify=ca,timeout=30);verified.raise_for_status()
        actual=verified.json()['item']['inputs'][0]['config']['policy']['value']
        if actual['linux']['malware']['mode']!='detect' or actual['global_telemetry_enabled']:
            raise RuntimeError('Defend baseline mode verification failed')

def verify_fleet_host(base,auth,ca,expected):
    response=requests.get(base+'/api/fleet/fleet_server_hosts/ea-fleet-host',auth=auth,verify=ca,timeout=30)
    response.raise_for_status();host=response.json()['item']
    if host.get('host_urls')!=[expected] or not host.get('is_default'):
        raise RuntimeError('Default Fleet Server host was not persisted')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--soc',required=True)
    p.add_argument('--ca',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--apply',action='store_true');p.add_argument('--password-file',type=Path)
    a=p.parse_args();plan=build(a.soc,a.ca.read_text());a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(plan,indent=2),encoding='utf-8')
    if not a.apply:return
    if not a.password_file:p.error('--apply requires --password-file')
    auth=('elastic',a.password_file.read_text().strip());host=urlparse(a.soc).hostname
    for item in plan:
        port=9200 if item['service']=='es' else 5601
        response=requests.request(item['method'],f'https://{host}:{port}'+item['path'],json=item['body'],auth=auth,
            headers={'kbn-xsrf':'ea'},verify=str(a.ca),timeout=120)
        # Never hide conflicts: a partial apply is reviewed before resume/update.
        response.raise_for_status()
    detection_only(f'https://{host}:5601',auth,str(a.ca))
    verify_fleet_host(f'https://{host}:5601',auth,str(a.ca),f'https://{host}:8220')
    print('Policies created; Linux malware mode=detect and global telemetry disabled. Enroll only after host/TLS review.')

if __name__=='__main__':main()
