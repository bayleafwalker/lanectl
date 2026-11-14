"""Installed-client issuer readiness and invalid-credential control, no secrets emitted."""
import json,os,re
from pathlib import Path
from importlib.metadata import distribution
from lanectl.coordination import CoordinationError,VuoroClient
from lanectl.lifecycle import ready_work,LIST
m=distribution('lanectl');vcs=json.loads(m.read_text('direct_url.json'))['vcs_info']
assert m.version=='0.2.10' and vcs['commit_id']=='686eb27cb9629da3ee36b4e0710945dcc3a7125e'
p=Path(os.environ['CREDENTIALS_DIRECTORY'])/'lanectl-runner'
c=VuoroClient('https://api.vuoro.cloud','homelab-analytics',lambda:p.read_text().strip())
h=c._request('/api/meta/v1/handshake');c.expected_environment=h['environment']['name'];catalog=c.discover()
f=ready_work(c);value=f.get('value');rows=value.get('items') if isinstance(value,dict) else None
assert f['state']=='observed' and isinstance(rows,list),'installed readiness remained uncertain'
print(json.dumps({'distribution':m.version,'release_commit':vcs['commit_id'],'endpoint':c.endpoint,'catalog_revision':catalog['revision'],'ready_state':f['state'],'ready_count':len(rows)},sort_keys=True))
bad=VuoroClient(c.endpoint,c.repo_id,lambda:'lanectl-deliberately-invalid-not-a-token',expected_environment=c.expected_environment);bad._catalog=catalog
try:bad.invoke(bad.envelope(LIST,{},None))
except CoordinationError as exc:
 match=re.fullmatch(r'owner refused: ([a-z][a-z0-9-]{0,63}) \(HTTP ([0-9]{3})\)',str(exc))
 assert match and int(match[2]) in (401,403),'negative credential control did not reach authenticated refusal'
 print(json.dumps({'control':'synthetic-invalid-runner','refused':True,'code':match[1],'http':int(match[2])},sort_keys=True))
else:raise AssertionError('invalid runner was accepted')
