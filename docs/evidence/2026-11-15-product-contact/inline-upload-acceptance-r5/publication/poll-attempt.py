from pathlib import Path
from datetime import datetime,timezone
import json,os,subprocess
from lanectl.events import open_log,project_items
from lanectl.config import load_lane
from lanectl.sandbox import from_lane
item='hla-source-row-upload';view=project_items(open_log().read()).get(item)
assert view is not None
user_env=dict(os.environ,XDG_RUNTIME_DIR='/run/user/1000',DBUS_SESSION_BUS_ADDRESS='unix:path=/run/user/1000/bus')
units=[]
for attempt in view.attempts:
 aid=attempt['attempt_id'];unit=from_lane(load_lane('implement').sandbox,('/projects/dev/_wt/lanes/'+aid,),2820,attempt_id=aid).unit
 raw=subprocess.check_output(['systemctl','--user','show',unit,'-pLoadState','-pActiveState','-pSubState','-pMainPID','-pResult'],text=True,env=user_env)
 info=dict(line.split('=',1) for line in raw.splitlines() if '=' in line)
 units.append({'id':aid,'model':attempt['model'],'unit':unit,'unit_state':info,'finished':attempt.get('finished'),'decision':attempt.get('decision'),'infra':attempt.get('infra')})
proof={'measured_at':datetime.now(timezone.utc).isoformat(),'item_id':item,'release_revision':view.release_revision,'item_state':view.state,'actual_claims_recorded':len(view.attempts),'maximum_actual_implementation_attempts':2,'attempts':units,'canonical_release_commit':'03d9614ade9e65dd31c3a40e55e5c9f21e0d3b5a','product_delivery':'UNOBSERVED','live_parent':'hla-source-row-upload-coordinator-20261115.service','exec_session':41424,'note':'Live ledger, not a stored snapshot, decides remaining attempts. Active Result=success is provisional. publication-run-state attempts_observed=0 is pre-admission history. Audit genuine startup failures separately; never relabel model timeout/errors as infra or reset by revision.'}
Path(__file__).with_name('live-attempt.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof,indent=2),flush=True)
