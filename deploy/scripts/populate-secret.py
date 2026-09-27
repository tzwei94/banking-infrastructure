#!/usr/bin/env python3
"""Read protected JSON from stdin. Secret values never enter Terraform or command arguments."""
import argparse,json,subprocess,sys,tempfile,os
p=argparse.ArgumentParser();p.add_argument('secret_arn');p.add_argument('--region',default='ap-southeast-1');a=p.parse_args()
data=json.load(sys.stdin)
if not isinstance(data,dict) or not data: raise SystemExit('Expected a nonempty JSON object')
with tempfile.NamedTemporaryFile(mode='w',suffix='.json') as f:
    os.chmod(f.name,0o600);json.dump(data,f);f.flush()
    subprocess.run(['aws','--region',a.region,'secretsmanager','put-secret-value','--secret-id',a.secret_arn,'--secret-string','file://'+f.name],check=True,stdout=subprocess.DEVNULL)
print('Secret version stored')
