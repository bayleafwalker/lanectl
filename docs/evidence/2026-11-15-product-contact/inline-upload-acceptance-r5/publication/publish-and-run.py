from pathlib import Path
from datetime import datetime,timezone
import json,os,re,shlex,shutil,subprocess,time,tomllib
import xml.etree.ElementTree as ET
from lanectl import cli,runner,specification as spec
from lanectl.config import load_release,load_repos,load_lane
from lanectl.events import open_log,project_items

root=Path('/projects/dev/lanectl')
scratch=Path('/tmp/hla-inline-upload-official-r5-20261115')
packet=root/'docs/evidence/2026-11-15-product-contact/inline-upload-acceptance-r5'
draft=scratch/'qualified-draft';item='hla-source-row-upload';dest=root/'backlog'/item
binding=json.loads((scratch/'source-binding.json').read_text())
reference=json.loads((scratch/'official-base-proof.json').read_text())['cases']
state={'phase':'preflight','item':item,'total_outcome_attempt_limit':2,'candidate':'UNOBSERVED'}
os.environ.setdefault('XDG_RUNTIME_DIR','/run/user/1000')
os.environ.setdefault('DBUS_SESSION_BUS_ADDRESS','unix:path=/run/user/1000/bus')
def save(**values):
 state.update(values);state['measured_at']=datetime.now(timezone.utc).isoformat()
 (scratch/'publication-run-state.json').write_text(json.dumps(state,indent=2)+'\n')
def command(*args):return subprocess.run(args,check=True,text=True,capture_output=True)
def require_pristine(events,records):
 assert not records,'Existing release already delivers this Work; do not duplicate/reset it'
 assert not any(e.get('item_id')==item or e.get('data',{}).get('work')=='homelab-analytics#1587' for e in events),'Outcome already has history; do not reset attempts'
def records():
 found=[]
 for p in (root/'backlog').glob('*/release.toml'):
  raw=tomllib.loads(p.read_text())
  if raw.get('id')==item or raw.get('work')=='homelab-analytics#1587':found.append(str(p))
 return found
# Exercise the actual duplicate/outcome-history predicate before any effect.
require_pristine([],[])
for events,prior in [([{'item_id':item,'data':{}}],[]),([],['existing-work-release']),([{'item_id':'another-id','data':{'work':'homelab-analytics#1587'}}],[])]:
 try:require_pristine(events,prior)
 except AssertionError:pass
 else:raise AssertionError('Pristine-outcome guard accepted existing history')
save(pristine_guard_negative_controls=3)
log=open_log();require_pristine(log.read(),records())
assert not dest.exists() and spec.release_digest(draft)==binding['release_digest']
assert spec.validate_for_publish(draft)==[]
assert json.loads((draft/'specification.json').read_text())['review']['verdict']=='accept'
assert command('git','-C',str(root),'branch','--show-current').stdout.strip()=='main'
command('git','-C',str(root),'diff','--exit-code');command('git','-C',str(root),'diff','--cached','--exit-code')
assert command('git','-C',str(root),'rev-parse','HEAD').stdout==command('git','-C',str(root),'rev-parse','origin/main').stdout
repo=load_repos()['homelab-analytics'];lane=load_lane('implement')
assert lane.max_attempts==2 and lane.size_budget_lines['M']==700
for ref in ['main','origin/main']:
 assert command('git','-C',str(repo.path),'rev-parse',ref).stdout.strip()==binding['base_sha']
timer=command('systemctl','--user','is-active','lanectl-tick.timer').stdout.strip()
assert timer=='active','Unexpected scheduler state; preserve and investigate'
save(timer_initial=timer,phase='quiesce-publication')
command('systemctl','--user','stop','lanectl-tick.timer')
completed=False;claim=None
try:
 assert command('systemctl','--user','show','lanectl-tick.timer','-pActiveState','--value').stdout.strip()=='inactive'
 deadline=time.monotonic()+45
 while command('systemctl','--user','show','lanectl-tick.service','-pActiveState','--value').stdout.strip()!='inactive':
  assert time.monotonic()<deadline,'Existing tick remains active; do not race it'
  time.sleep(0.2)
 require_pristine(log.read(),records())
 shutil.copytree(draft,dest)
 assert load_release(dest).draft and spec.validate_for_publish(dest)==[]
 actual=spec.run_tests_at
 def recorded(*args,**kwargs):
  values=list(args);assert values[3]==repo.test_cmd
  junit=scratch/'publication-base-junit.xml';assert not junit.exists()
  values[3]='env -u LD_LIBRARY_PATH -u HLA_FORCE_BROWSER_FALLBACK PLAYWRIGHT_BROWSERS_PATH='+shlex.quote(str(scratch/'absent-native-browser-cache'))+' '+values[3]+' --junitxml='+shlex.quote(str(junit))+' --basetemp='+shlex.quote(str(scratch/'pytest-publication-base'))
  code,output=actual(*values,**kwargs)
  (scratch/'publication-base-lint.log').write_text(output)
  cases=list(ET.parse(junit).getroot().iter('testcase'))
  names=[c.attrib['name'] for c in cases]
  assert len(names)==len(set(names))==len(reference) and set(names)==set(reference)
  assert not any(c.find('error') is not None or c.find('skipped') is not None for c in cases)
  statuses={c.attrib['name']:'failed' if c.find('failure') is not None else 'passed' for c in cases}
  assert code==1 and statuses==reference,'Publication base population differs'
  (scratch/'publication-base-proof.json').write_text(json.dumps({'code':code,'cases':statuses,'exact_population_qualified':True,'passed':35,'failed':57,'errors':0,'skips':0,'instrumented_test_command':values[3],'release_digest':spec.release_digest(dest),'candidate':'UNOBSERVED'},indent=2)+'\n')
  return code,output
 spec.run_tests_at=recorded
 try:assert cli.main(['backlog','publish',item])==0
 finally:spec.run_tests_at=actual
 assert not load_release(dest).draft and spec.release_digest(dest)==binding['release_digest']
 view=project_items(log.read())[item];assert view.state=='ready' and len(view.attempts)==0 and view.release_revision==1
 save(phase='published-before-git',release_digest=binding['release_digest'],attempts_observed=0)
 publication=packet/'publication';publication.mkdir()
 for name in ['publish-and-run.py','publication-base-lint.log','publication-base-junit.xml','publication-base-proof.json']:
  shutil.copy2(scratch/name,publication/name)
 command('git','-C',str(root),'add',str(dest),str(publication))
 committed=command('git','-C',str(root),'commit','-m','backlog: publish fully reviewed inline stale-source upload')
 print(committed.stdout,flush=True)
 pushed=command('git','-C',str(root),'push','origin','main');print(pushed.stderr,flush=True)
 completed=True;save(phase='published-durable',canonical_commit=command('git','-C',str(root),'rev-parse','HEAD').stdout.strip())
 view=project_items(log.read())[item];assert view.state=='ready' and len(view.attempts)==0
 claim=runner.admit('implement',log,only=item)
 if not isinstance(claim,runner.Claim):
  save(phase='published-awaiting-admission',admission=claim)
  print(claim,flush=True)
 else:
  assert claim.rel.id==item and claim.rel.revision==1 and claim.attempt_id==item+'-a1'
  save(phase='native-attempt',attempt_id=claim.attempt_id,model=claim.model)
  print('claimed '+claim.attempt_id+' -> '+claim.model,flush=True)
finally:
 view=project_items(log.read()).get(item)
 if not completed:
  if view is not None and view.state in ('ready','requeued','rejected') and not view.attempts:
   log.append('item.parked',{'reason':'Coordinator interrupted before durable publication/admission; reviewed bytes and zero attempts retained.'},item_id=item)
  elif view is None and dest.exists():
   shutil.copy2(draft/'release.toml',dest/'release.toml')
 if timer=='active':command('systemctl','--user','start','lanectl-tick.timer')
 save(timer_restored=True)
if isinstance(claim,runner.Claim):
 result=runner.execute(claim,log)
 view=project_items(log.read())[item]
 save(phase='attempt-returned',result=result,current_item_state=view.state,actual_attempts_observed=len(view.attempts))
 print(result,flush=True)
