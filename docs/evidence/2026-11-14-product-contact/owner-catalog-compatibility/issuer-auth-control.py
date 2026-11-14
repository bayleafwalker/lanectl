"""Measure schema compatibility and readiness; emit no credential or work values."""
import json,os,sys,subprocess
from pathlib import Path
sys.path.insert(0,'/projects/dev/_wt/lanectl-owner-literals-20261114/src')
from lanectl.coordination import VuoroClient
from lanectl.lifecycle import READS,LIST,_schema_supported,ready_work
source=subprocess.check_output(['git','-C','/projects/dev/_wt/lanectl-owner-literals-20261114','rev-parse','HEAD'],text=True).strip()
assert source==sys.argv[1]
assert not subprocess.check_output(['git','-C','/projects/dev/_wt/lanectl-owner-literals-20261114','status','--porcelain'],text=True)
p=Path(os.environ['CREDENTIALS_DIRECTORY'])/'lanectl-runner'
c=VuoroClient('https://api.vuoro.cloud','homelab-analytics',lambda:p.read_text().strip())
h=c._request('/api/meta/v1/handshake');c.expected_environment=h['environment']['name'];catalog=c.discover()
ops=[]
for op in catalog['operations']:
 if op.get('name') not in (*READS,LIST):continue
 schemas={k:op.get(k) for k in ['input_schema','result_schema']}
 ops.append({'operation':op['name'],'schema_keys':{k:sorted(v) if isinstance(v,dict) else None for k,v in schemas.items()},'supported':{k:_schema_supported(v) for k,v in schemas.items()}})
f=ready_work(c);v=f.get('value')
print(json.dumps({'endpoint':c.endpoint,'catalog_revision':catalog['revision'],'client_source':source,'operations':ops,'ready_state':f['state'],'ready_count':len(v['items']) if f['state']=='observed' and isinstance(v,dict) and isinstance(v.get('items'),list) else None,'unknown_reason':f.get('reason') if f['state']=='unknown' else None},sort_keys=True))

from lanectl.coordination import CoordinationError
import re
bad=VuoroClient(c.endpoint,c.repo_id,lambda:'lanectl-deliberately-invalid-not-a-token',expected_environment=c.expected_environment)
bad._catalog=catalog
try:
 bad.invoke(bad.envelope(LIST,{},None))
except CoordinationError as exc:
 match=re.fullmatch(r'owner refused: ([a-z][a-z0-9-]{0,63}) \(HTTP ([0-9]{3})\)',str(exc))
 assert match and int(match[2]) in (401,403),'negative credential control did not reach authenticated refusal'
 print(json.dumps({'control':'synthetic-invalid-runner','refused':True,'code':match[1],'http':int(match[2])},sort_keys=True))
else:
 raise AssertionError('synthetic invalid runner was accepted')
