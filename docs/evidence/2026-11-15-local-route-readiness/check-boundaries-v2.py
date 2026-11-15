from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
import ast,contextlib,hashlib,importlib.util,json,os,shutil,tempfile,time,urllib.request
from lanectl import specification as spec
from lanectl.config import load_repos,load_lane
r=Path('/tmp/lanectl-local-readiness-20261115')
os.environ.update(XDG_RUNTIME_DIR='/run/user/1000',DBUS_SESSION_BUS_ADDRESS='unix:path=/run/user/1000/bus',LANECTL_LOCAL_BASE_URL='http://127.0.0.1:8020/v1')
actual=json.loads((r/'actual-local-return.json').read_text());case=json.loads((r/'public-probe-repo/case.json').read_text())
tree=ast.parse((r/'run-native.py').read_text())
outer=next(n for n in tree.body if isinstance(n,ast.Try) and any(isinstance(x,ast.Assign) and any(isinstance(t,ast.Tuple) for t in x.targets) for x in n.body))
assertions=[n for n in outer.body if isinstance(n,ast.Assert)]
assert len(assertions)==3
checks={}
for kind in ['valid','stale-nonce','wrong-number','foreign-origin']:
 response=json.loads(json.dumps(actual['response']));wire=json.loads(json.dumps(actual['wire_metadata']))
 if kind=='stale-nonce':response['checks']=[s.replace(case['probe_nonce'],'stale-probe') for s in response['checks']]
 if kind=='wrong-number':response['checks']=[s.replace('262145','262146') for s in response['checks']]
 if kind=='foreign-origin':wire[0]['url']='https://example.invalid/v1/chat/completions'
 env={'response':response,'case':case,'encoded':json.dumps(response),'requests':[w for w in wire if w['method']=='POST']}
 try:exec(compile(ast.Module(body=assertions,type_ignores=[]),'actual-native-probe-assertions','exec'),env);accepted=True
 except AssertionError:accepted=False
 assert accepted==(kind=='valid'),kind
 checks[kind]='accepted' if accepted else 'rejected'
(r/'checker-falsifiers.json').write_text(json.dumps(checks,indent=2)+'\n')
module_spec=importlib.util.spec_from_file_location('observed_lane_helper','/projects/dev/local-inference/scripts/lib/lane.py')
lane=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(lane)
wire=[];original_open=urllib.request.OpenerDirector.open

def counted(self,request,*args,**kwargs):
 wire.append({'url':request.full_url if hasattr(request,'full_url') else str(request),'method':request.get_method() if hasattr(request,'get_method') else 'GET'})
 return original_open(self,request,*args,**kwargs)
urllib.request.OpenerDirector.open=counted
Original=tempfile.TemporaryDirectory
class Retained(Original):
 def __exit__(self,*args):
  if self.name and Path(self.name).name.startswith('lanectl-spec-'):
   root=Path(self.name)
   for sub in ['runtime','checkout/.lanectl-spec']:
    path=root/sub
    if path.exists():shutil.copytree(path,r/'busy-v2-invocation'/sub,dirs_exist_ok=True)
  return super().__exit__(*args)
tempfile.TemporaryDirectory=Retained
started=time.monotonic()
try:
 with lane.lane_lock(['worker-fast'],purpose='lanectl-owned-busy-negative',wait=0):
  held=lane.holder();assert held is not None and held.get('pid')==os.getpid()
  try:
   spec._invoke(replace(load_repos()['lanectl'],path=r/'public-probe-repo'),load_lane('implement'),actual['source_probe_commit'],'local/worker-fast','Read case.json and write only .lanectl-spec/response.json. This public probe must be refused before model execution while its lane is held.',timeout_s=30)
  except ValueError as error:
   assert 'spec model failed' in str(error)
  else:raise AssertionError('Busy lane unexpectedly dispatched a native model')
 holder_after=lane.holder()
 assert holder_after is None or holder_after.get('pid')!=os.getpid(),'Owned inference lock was not released'
 status=json.loads((r/'busy-v2-invocation/runtime/status.json').read_text())
 assert status['outcome']=='failed' and status['exit_code']==3
 assert all(value==0 for value in (status.get('usage') or {}).values())
 assert 'lanectl-owned-busy-negative' in status['final_message_tail']
 assert not wire,'Busy refusal still sent a model request'
 proof={'busy_native_dispatch_refused':True,'adapter_exit':status['exit_code'],'model_requests_observed':len(wire),'owned_holder_pid_verified':True,'owned_lock_released':True,'global_lane_free_at_snapshot':holder_after is None,'elapsed_s':round(time.monotonic()-started,3),'checker_falsifiers':checks,'public_probe_only':True,'governance_changed':False}
 (r/'busy-refusal-proof.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof),flush=True)
finally:urllib.request.OpenerDirector.open=original_open
