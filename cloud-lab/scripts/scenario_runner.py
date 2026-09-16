"""Bounded private-lab HTTP checks. Default is a plan, never an attack run."""
import argparse
from datetime import datetime, timezone
import hashlib
import http.client
import ipaddress
import json
from pathlib import Path
import socket
import ssl
import time
from urllib.parse import urlsplit
import uuid

LAB = ipaddress.ip_network('10.60.0.0/16')

def actions(scenario):
    if scenario == 'S0':
        return [('GET', '/', None), ('GET', '/wp-login.php', None)]
    if scenario == 'S1':
        return [('GET', path, None) for path in ('/ea-no-such-page', '/robots.txt', '/wp-json/')]
    if scenario == 'S2':
        return [('POST', '/wp-login.php', 'log=ea-nonexistent-user&pwd=ea-fixed-invalid-password')]*12
    if scenario == 'S3':
        return [('GET', '/?ea_probe=1%27%20OR%201%3D1--', None)]
    raise ValueError('Only S0-S3 have automated HTTP checks')

def target(url, local_test=False):
    parsed=urlsplit(url)
    if (parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query
            or parsed.fragment or not parsed.hostname):
        raise ValueError('Use an origin without credentials/path/query')
    if parsed.scheme!='https' and not (local_test and parsed.scheme=='http'):
        raise ValueError('HTTPS with a trusted certificate is required')
    port=parsed.port or (443 if parsed.scheme=='https' else 80)
    if not local_test and port!=443:raise ValueError('AWS checks must use the ALB HTTPS listener')
    addresses=sorted({item[4][0] for item in socket.getaddrinfo(parsed.hostname,port,type=socket.SOCK_STREAM)})
    if not addresses:raise ValueError('No target address')
    for value in addresses:
        ip=ipaddress.ip_address(value)
        if local_test:
            if not ip.is_loopback:raise ValueError('Local rehearsal is loopback only')
        elif ip not in LAB:raise ValueError('Target is outside the declared 10.60.0.0/16 lab')
    return parsed, addresses

def request(parsed, address, method, path, body, ca, host_header=None):
    # Connect to the already validated address; DNS is not resolved a second time.
    conn=http.client.HTTPConnection(address,parsed.port or (443 if parsed.scheme=='https' else 80),timeout=15)
    conn.connect()
    try:
        if parsed.scheme=='https':
            context=ssl.create_default_context(cafile=str(ca))
            conn.sock=context.wrap_socket(conn.sock,server_hostname=parsed.hostname)
        headers={'Host':host_header or parsed.netloc,'User-Agent':'EvidenceAtlas-LabCheck/1.0','Connection':'close'}
        if body is not None:headers['Content-Type']='application/x-www-form-urlencoded'
        started=datetime.now(timezone.utc).isoformat()
        conn.request(method,path,body=body,headers=headers)
        response=conn.getresponse();data=response.read(1024*1024+1)
        if len(data)>1024*1024:raise ValueError('Response exceeds 1 MiB; stopped')
        return {'timestamp':started,'method':method,'path':path,'status':response.status,
                'request_id':response.getheader('X-Request-ID'),'location':response.getheader('Location'),
                'body_bytes':len(data),'body_sha256':hashlib.sha256(data).hexdigest()}
    finally:conn.close()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--target',required=True);p.add_argument('--scenario',choices=['S0','S1','S2','S3'],required=True)
    p.add_argument('--ca',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--execute',action='store_true');p.add_argument('--local-test',action='store_true')
    p.add_argument('--dvwa',action='store_true',help='Host=dvwa.lab; only S3 probe (not authenticated exploitation)')
    a=p.parse_args()
    if a.dvwa and a.scenario!='S3':p.error('--dvwa is only available for S3')
    # Offline plan does not resolve DNS or contact the target.
    planned=actions(a.scenario)
    report={'record_type':'http-plan','schema_version':'1.1','scenario_id':a.scenario,'run_id':str(uuid.uuid4()),'target':a.target,
            'scope':'local-docker' if a.local_test else 'private-aws-lab',
            'executed':False,'actions':planned,'results':[],
            'note':'HTTP status is evidence of a response, not proof of compromise or SIEM detection.'}
    if a.output.exists():p.error('Use a new output path; previous results are preserved')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    error=None
    try:
        if a.execute:
            parsed,addresses=target(a.target,a.local_test)
            if parsed.scheme=='https' and (not a.ca or not a.ca.is_file()):raise ValueError('Provide --ca')
            report.update(record_type='http-receipt',executed=True,executed_at=datetime.now(timezone.utc).isoformat(),addresses=addresses)
            for method,path,body in planned:
                report['results'].append(request(parsed,addresses[0],method,path,body,a.ca,'dvwa.lab' if a.dvwa else None))
                time.sleep(.25)
                # Never follow redirects, including redirects back into a private network.
    except Exception as exc:
        error=str(exc);report['error']=error
    finally:a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if error:raise SystemExit(error)
    print(json.dumps({'report':str(a.output),'executed':report['executed'],'requests':len(report['results'])}))

if __name__=='__main__':main()
