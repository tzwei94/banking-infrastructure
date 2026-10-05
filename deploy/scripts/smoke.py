#!/usr/bin/env python3
import base64,json,os,ssl,urllib.request,urllib.error,uuid
mode=os.environ.get('READ_ONLY_SMOKE','false')
if mode not in ('true','false'): raise SystemExit('READ_ONLY_SMOKE must be true or false')
base=os.environ['API_URL'].rstrip('/')
if not base.startswith('https://'): raise SystemExit('API_URL must use HTTPS')
context=ssl.create_default_context()
credentials=base64.b64encode((os.environ['TOKEN_USERNAME']+':'+os.environ['TOKEN_PASSWORD']).encode()).decode()
login=urllib.request.Request(base+'/auth/token',method='POST',headers={'Authorization':'Basic '+credentials})
with urllib.request.urlopen(login,context=context,timeout=15) as response:
 token=json.load(response)
assert token['token_type']=='Bearer' and token['expires_in']==900
api_token=token['access_token']
account='00000000-0000-0000-0000-000000000001'
def request(path,body=None,key=None,auth=True):
 headers={'Content-Type':'application/json'}
 if auth: headers['Authorization']='Bearer '+api_token
 if key: headers['Idempotency-Key']=key
 req=urllib.request.Request(base+path,data=json.dumps(body).encode() if body else None,headers=headers)
 with urllib.request.urlopen(req,context=context,timeout=15) as r: return json.load(r)
if mode=='true':
 assert request('/readyz',auth=False)['status']=='UP'
 assert request('/livez',auth=False)['status']=='UP'
 version=request('/version',auth=False)
 assert isinstance(version.get('version'),str) and isinstance(version.get('source'),str)
 print('PASS: Basic token issuance and public readiness, liveness and version; read-only release smoke')
 raise SystemExit(0)
prefix='/accounts/'+account
before=request(prefix+'/balance')['balance']
key=str(uuid.uuid4())
a=request(prefix+'/deposits',{'amount':'0.01'},key)
assert request(prefix+'/deposits',{'amount':'0.01'},key)==a
request(prefix+'/withdrawals',{'amount':'0.01'},str(uuid.uuid4()))
assert request(prefix+'/balance')['balance']==before
try: request(prefix+'/balance',auth=False); raise AssertionError('anonymous request accepted')
except urllib.error.HTTPError as e: assert e.code==401
print('PASS: Basic token issuance, authenticated balance, deposit, withdrawal, retry and anonymous denial')
