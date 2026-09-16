"""Provision scoped application users through an already-open SSM RDS tunnel.

Master credentials are retrieved locally, never sent in an SSM command. TLS
validates the RDS hostname even though the TCP socket goes through localhost.
No reset/drop of an existing database is performed.
"""
import argparse
import json
import re
import socket

def provision(connection,applications):
    with connection.cursor() as cursor:
        cursor.execute("SHOW SESSION STATUS LIKE 'Ssl_cipher'")
        cipher=cursor.fetchone()
        if not cipher or not cipher[1]:raise ValueError('Database session is not encrypted')
        for secret in applications:
            database=secret['dbname'];user=secret['username']
            if database not in ('wordpress','dvwa') or not re.fullmatch('[a-z][a-z0-9_]{0,31}',user) or user in ('root','admin'):
                raise ValueError('Only dedicated wordpress/dvwa users are allowed')
            cursor.execute(f'CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4')
            cursor.execute("CREATE USER IF NOT EXISTS %s@'%%' IDENTIFIED BY %s REQUIRE SSL",(user,secret['password']))
            cursor.execute("ALTER USER %s@'%%' IDENTIFIED BY %s REQUIRE SSL",(user,secret['password']))
            cursor.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE,CREATE,ALTER,DROP,INDEX ON `{database}`.* TO %s@'%%'",(user,))
    connection.commit()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',required=True);parser.add_argument('--region',default='ap-northeast-2')
    parser.add_argument('--master-secret',required=True);parser.add_argument('--wordpress-secret',required=True)
    parser.add_argument('--dvwa-secret',required=True);parser.add_argument('--ca',required=True)
    parser.add_argument('--tunnel-port',type=int,default=13306)
    args=parser.parse_args()
    import boto3
    import pymysql
    client=boto3.Session(profile_name=args.profile,region_name=args.region).client('secretsmanager')
    read=lambda arn:json.loads(client.get_secret_value(SecretId=arn)['SecretString'])
    master=read(args.master_secret);apps=[read(args.wordpress_secret),read(args.dvwa_secret)]
    if any(app['host']!=master['host'] for app in apps):raise ValueError('Application/master endpoint mismatch')
    connection=pymysql.connect(host=master['host'],user=master['username'],password=master['password'],
        ssl_ca=args.ca,ssl_verify_cert=True,ssl_verify_identity=True,defer_connect=True,autocommit=True)
    sock=socket.create_connection(('127.0.0.1',args.tunnel_port),timeout=20)
    try:
        connection.connect(sock=sock);provision(connection,apps)
    finally:connection.close();sock.close()
    print('Provisioned two dedicated application users over verified TLS; existing data retained')

if __name__=='__main__':main()
