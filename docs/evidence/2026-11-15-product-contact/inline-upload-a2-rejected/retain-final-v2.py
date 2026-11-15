from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,subprocess,tempfile
from lanectl.events import open_log,project_items
item='hla-source-row-upload';aid=item+'-a2'
base='b2d0fe393ac0971e906cce275e91f45e94422593'
frozen='38354937708ffe7f9699c836e41e65abca603b7f354c92cba5f0a482263162d3'
canonical=Path('/projects/dev/homelab-analytics')
log=open_log();events=log.read();view=project_items(events)[item]
assert len(view.attempts)==2 and view.attempts[-1]['attempt_id']==aid
finished=view.attempts[-1].get('finished')
assert finished is not None,'FINAL MODEL IS STILL ACTIVE: no source inspection allowed'
head=finished['head_sha'];seed=finished['seed_sha']
assert head and seed
out=Path('/tmp/hla-inline-upload-official-r5-20261115/final-immutable')
out.mkdir(exist_ok=True)
def run(*args):
 r=subprocess.run(args,capture_output=True,text=True)
 if r.returncode:
  (out/'retention-command-failure.json').write_text(json.dumps({'args':args,'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr},indent=2)+'\n')
  print(r.stdout+r.stderr,flush=True)
 r.check_returncode()
 return r
def git(repo,*args):return run('git','-C',str(repo),*args).stdout
source=canonical
probe=subprocess.run(['git','-C',str(source),'cat-file','-e',head+'^{commit}'],capture_output=True)
if probe.returncode:
 source=Path('/projects/dev/_wt/lanes')/aid
 assert subprocess.run(['git','-C',str(source),'cat-file','-e',head+'^{commit}'],capture_output=True).returncode==0
with tempfile.TemporaryDirectory(prefix='hla-final-source-freeze-') as tmp:
 bare=Path(tmp)/'source.git';run('git','init','--bare',str(bare))
 git(bare,'fetch',str(canonical),base)
 git(bare,'fetch',str(source),head+':refs/heads/frozen-final')
 assert git(bare,'rev-parse','frozen-final').strip()==head
 git(bare,'merge-base','--is-ancestor',seed,head)
 assert not (bare/'objects/info/alternates').exists()
 git(bare,'fsck','--strict')
 git(bare,'bundle','create',str(out/'final-source.bundle'),'refs/heads/frozen-final','^'+base)
 num=git(bare,'diff','--numstat',seed,head);(out/'worker-numstat.txt').write_text(num)
 (out/'worker-source.diff').write_text(git(bare,'diff',seed,head))
 names=git(bare,'diff','--name-status',seed,head);(out/'worker-name-status.txt').write_text(names)
 counts=[line.split('\t',2) for line in num.splitlines()]
 binary=[path for a,b,path in counts if not a.isdigit() or not b.isdigit()]
 total=sum(int(a)+int(b) for a,b,_ in counts if a.isdigit() and b.isdigit())
 checks={}
 for name in ['tests/test_freshness_remediation_flow.py','tests/test_file_format.py','tests/test_manual_upload_and_preview_api.py','tests/test_web_auth.py']:
  old=subprocess.check_output(['git','-C',str(bare),'show',base+':'+name])
  new=subprocess.check_output(['git','-C',str(bare),'show',head+':'+name])
  checks[name]={'base_sha256':hashlib.sha256(old).hexdigest(),'head_sha256':hashlib.sha256(new).hexdigest(),'equal':old==new}
 acceptance=subprocess.check_output(['git','-C',str(bare),'show',head+':tests/test_hla1587_acceptance.py'])
 frozen_actual=hashlib.sha256(acceptance).hexdigest()
 assert frozen_actual==frozen
 with tempfile.TemporaryDirectory(prefix='hla-final-bundle-restore-') as restoretmp:
  restore=Path(restoretmp)/'restored.git';run('git','init','--bare',str(restore))
  git(restore,'fetch',str(canonical),base)
  git(restore,'bundle','verify',str(out/'final-source.bundle'))
  git(restore,'fetch',str(out/'final-source.bundle'),'refs/heads/frozen-final:refs/heads/restored')
  assert git(restore,'rev-parse','restored').strip()==head
  assert git(restore,'rev-parse',seed).strip()==seed
  assert not (restore/'objects/info/alternates').exists()
  git(restore,'fsck','--strict')
 data={'measured_at':datetime.now(timezone.utc).isoformat(),'item':item,'attempt_id':aid,'actual_claims':2,'outcome_cap':2,'finished':finished,'head':head,'seed':seed,'worker_added_plus_deleted':total,'binary_files':binary,'M700_within':total<=700 and not binary,'preserved_base_tests':checks,'frozen_acceptance_sha256':frozen_actual,'isolated_bundle_restore_fsck_exit':0,'source_adopted':False,'product_delivery':'UNOBSERVED'}
 (out/'source-proof.json').write_text(json.dumps(data,indent=2)+'\n')
 selected=[]
 for e in events:
  if e.get('item_id')==item and e.get('data',{}).get('attempt_id')==aid and e['type'] in ['item.claimed','attempt.finished','gate.result','decision.recorded','experiment.recorded','usage.recorded']:
   d=e['data']
   if e['type']=='item.claimed': d={k:d.get(k) for k in ['attempt_id','model','worker','lane','release_revision','prompt_feedback_version']}
   selected.append({'ts':e['ts'],'type':e['type'],'data':d})
 (out/'measured-events.json').write_text(json.dumps(selected,indent=2)+'\n')
 print(json.dumps(data,indent=2),flush=True)
