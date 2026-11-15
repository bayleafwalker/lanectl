from pathlib import Path
from datetime import datetime,timezone
import json,os
from lanectl import runner,specification as spec
from lanectl.config import load_release,load_lane
from lanectl.events import open_log,project_items
r=Path('/tmp/hla-inline-upload-official-r5-20261115');item='hla-source-row-upload'
os.environ.setdefault('XDG_RUNTIME_DIR','/run/user/1000')
os.environ.setdefault('DBUS_SESSION_BUS_ADDRESS','unix:path=/run/user/1000/bus')
log=open_log();view=project_items(log.read())[item]
assert len(view.attempts)==1 and view.state=='requeued'
prior=view.attempts[0]
assert prior['attempt_id']==item+'-a1' and prior['decision']=='rejected' and not prior.get('infra')
rel=load_release(Path('/projects/dev/lanectl/backlog')/item)
assert rel.revision==1 and not rel.draft and spec.release_digest(rel.release_dir)=='22bbdfd2cf561c877a8aab944eeafa8714a685ca5da3f49d38d92b9ab041782a'
lane=load_lane('implement');assert lane.max_attempts==2 and lane.size_budget_lines['M']==700
state={'measured_at':datetime.now(timezone.utc).isoformat(),'item':item,'phase':'before-second-admission','actual_prior_claims':1,'total_outcome_cap':2,'release_revision':1}
def save(**data):
 state.update(data);state['measured_at']=datetime.now(timezone.utc).isoformat()
 (r/'a2-run-state.json').write_text(json.dumps(state,indent=2)+'\n')
save()
claim=runner.admit('implement',log,only=item)
if not isinstance(claim,runner.Claim):
 save(phase='not-admitted',reason=claim)
 print(claim,flush=True)
else:
 assert claim.attempt_id==item+'-a2' and claim.model!=prior['model']
 current=project_items(log.read())[item]
 feedback=runner._retry_feedback(log.read(),item,1,claim.attempt_id)
 assert len(current.attempts)==2 and any('server freshness/date/status/recovery' in f['reason'] for f in feedback)
 save(phase='native-second-attempt',attempt_id=claim.attempt_id,model=claim.model,actual_claims=2,feedback=feedback,candidate='UNOBSERVED')
 print('claimed '+claim.attempt_id+' -> '+claim.model,flush=True)
 result=runner.execute(claim,log)
 current=project_items(log.read())[item]
 save(phase='second-attempt-returned',result=result,actual_claims=len(current.attempts),item_state=current.state)
 print(result,flush=True)
