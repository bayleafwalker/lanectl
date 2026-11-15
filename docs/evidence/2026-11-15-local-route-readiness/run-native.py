from pathlib import Path
from dataclasses import replace
from datetime import datetime,timezone
import hashlib,json,os,shutil,subprocess,tempfile,time,urllib.request,uuid
from lanectl import specification as spec
from lanectl.config import load_repos,load_lane
r=Path('/tmp/lanectl-local-readiness-20261115');repo=r/'public-probe-repo'
os.environ['XDG_RUNTIME_DIR']='/run/user/1000'
os.environ['DBUS_SESSION_BUS_ADDRESS']='unix:path=/run/user/1000/bus'
os.environ['LANECTL_LOCAL_BASE_URL']='http://127.0.0.1:8020/v1'
status=subprocess.run(['python3','/projects/dev/local-inference/scripts/lib/lane.py','status'],capture_output=True,text=True)
raw=status.stdout.strip()
if status.returncode==0 and raw=='free':holder=None;lane_state='free'
else:
 try:full=json.loads(raw)
 except ValueError:full={}
 holder={k:full.get(k) for k in ['pid','models','started_at']};lane_state='held' if status.returncode==3 else 'could-not-check'
(r/'lane-preflight.json').write_text(json.dumps({'measured_at':datetime.now(timezone.utc).isoformat(),'exit':status.returncode,'state':lane_state,'holder':holder,'purpose_withheld':True},indent=2)+'\n')
assert lane_state=='free','Respect existing inference lock; do not load/evict a model'
assert not Path('/etc/opencode').is_dir() or not any(Path('/etc/opencode').iterdir())
repo.mkdir()
case={'probe_nonce':'local-route-'+uuid.uuid4().hex[:12],'trusted_proposal_bytes':119745,'max_trusted_proposal_bytes':262144,'max_model_response_bytes':65536,'max_intent_bytes':16384,'rule':'Compare trusted input only with max_trusted_proposal_bytes. Keep the independent output/intent bounds unchanged.'}
(repo/'case.json').write_text(json.dumps(case,indent=2)+'\n')
(repo/'README.md').write_text('Synthetic public operational probe only. Read case.json and write only .lanectl-spec/response.json. No credentials, outside repositories, network tools, deployments or code changes. This does not qualify product quality or private work.\n')
subprocess.run(['git','init','-q','-b','main',str(repo)],check=True)
subprocess.run(['git','-C',str(repo),'add','case.json','README.md'],check=True)
subprocess.run(['git','-C',str(repo),'commit','-q','-m','test: public local route probe'],check=True)
base=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
prompt='Read case.json in this tiny public probe repository. Compare its trusted_proposal_bytes only to max_trusted_proposal_bytes and assess whether the described separate-bound rule is sound. Identify the exact first invalid trusted-input byte count. Do not modify source or case.json, access credentials/outside directories/network/tools/providers, install anything, or delegate. Write ONLY .lanectl-spec/response.json as JSON with exactly four keys: verdict(accept or revise), reason(nonempty string), trivial_pass(nonempty explanation of the wrong shared-bound check), checks(nonempty array of strings). Include the exact probe_nonce and the decimal input bound, given input size and first-invalid byte count in checks. Keep it brief. This is a runtime/tool/route probe, not product qualification.'
wire=[];original_open=urllib.request.OpenerDirector.open

def observed_open(self,request,*args,**kwargs):
 url=request.full_url if hasattr(request,'full_url') else str(request)
 entry={'url':url,'method':request.get_method() if hasattr(request,'get_method') else 'GET'}
 body=getattr(request,'data',None)
 if body:
  entry['request_bytes']=len(body);entry['request_sha256']=hashlib.sha256(body).hexdigest()
  try:entry['model']=json.loads(body).get('model')
  except ValueError:entry['model']=None
 try:
  response=original_open(self,request,*args,**kwargs);entry['status']=response.status;return response
 except BaseException as error:
  entry['error_type']=type(error).__name__;raise
 finally:wire.append(entry)
urllib.request.OpenerDirector.open=observed_open
Original=tempfile.TemporaryDirectory
class Retained(Original):
 def __exit__(self,*args):
  if self.name and Path(self.name).name.startswith('lanectl-spec-'):
   owned=Path(self.name)
   for sub in ['runtime','checkout/.lanectl-spec']:
    path=owned/sub
    if path.exists():shutil.copytree(path,r/'invocation'/sub,dirs_exist_ok=True)
  return super().__exit__(*args)
tempfile.TemporaryDirectory=Retained
started=time.monotonic()
try:
 response,usage=spec._invoke(replace(load_repos()['lanectl'],path=repo),load_lane('implement'),base,'local/worker-fast',prompt,timeout_s=120)
 spec._review(response)
 encoded=json.dumps(response)
 assert response['verdict']=='accept' and case['probe_nonce'] in encoded
 assert all(str(n) in encoded.replace(',','') for n in [119745,262144,262145])
 requests=[w for w in wire if w['method']=='POST']
 assert requests and all(w['url']=='http://127.0.0.1:8020/v1/chat/completions' and w.get('model')=='worker-fast' and w.get('status')==200 for w in requests)
 proof={'measured_at':datetime.now(timezone.utc).isoformat(),'official_invoke_returned':True,'model':'local/worker-fast','response':response,'usage':usage,'elapsed_s':round(time.monotonic()-started,3),'wire_metadata':wire,'prompt_and_credentials_not_in_wire_log':True,'operational_scope':'Real native local model read/write and pinned loopback relay only; no product, GPU quality, private/restricted work or routing promotion claim.','governance_changed':False,'source_probe_commit':base}
 (r/'actual-local-return.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof),flush=True)
except BaseException as error:
 (r/'native-error.json').write_text(json.dumps({'type':type(error).__name__,'message':str(error),'elapsed_s':round(time.monotonic()-started,3),'wire_metadata':wire,'governance_changed':False},indent=2)+'\n')
 raise
finally:
 urllib.request.OpenerDirector.open=original_open
