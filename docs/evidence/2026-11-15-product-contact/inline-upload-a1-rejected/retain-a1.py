from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,shutil,subprocess,tempfile
from lanectl.events import open_log
r=Path('/tmp/hla-inline-upload-official-r5-20261115')
d=Path('/projects/dev/lanectl/docs/evidence/2026-11-15-product-contact/inline-upload-a1-rejected');d.mkdir(exist_ok=True)
repo=Path('/projects/dev/homelab-analytics');base='b2d0fe393ac0971e906cce275e91f45e94422593';head='a3e4709e9882315c69c107bdf5bc698268f1c16a';seed='8bf6645cf0fda379ff564549fbbc704b7df660c5';aid='hla-source-row-upload-a1'
def git(*args):return subprocess.check_output(['git','-C',str(repo),*args])
assert git('rev-parse','refs/heads/lane/'+aid).decode().strip()==head
subprocess.run(['git','-C',str(repo),'bundle','create',str(d/'rejected-source.bundle'),'refs/heads/lane/'+aid,'^'+base],check=True,capture_output=True)
num=git('diff','--numstat',seed,head).decode();(d/'worker-numstat.txt').write_text(num)
counts=[line.split('\t',2) for line in num.splitlines()];assert sum(int(a)+int(b) for a,b,_ in counts)==685
(d/'worker-source.diff').write_bytes(git('diff',seed,head))
for n in ['a1-integrator-feedback.json']:
 shutil.copy2(r/n,d/n)
shutil.copy2(Path('/home/bayleaf/.local/state/lanectl/runs')/(aid+'.json'),d/'native-status.json')
records=[]
for event in open_log().read():
 data=event.get('data',{})
 if event.get('item_id')=='hla-source-row-upload' and data.get('attempt_id')==aid and event['type'] in ['item.claimed','attempt.finished','gate.result','decision.recorded','experiment.recorded','usage.recorded']:
  if event['type']=='item.claimed':data={k:data.get(k) for k in ['attempt_id','model','worker','lane','release_revision','prompt_feedback_version']}
  records.append({'ts':event['ts'],'type':event['type'],'data':data})
(d/'measured-events.json').write_text(json.dumps(records,indent=2)+'\n')
with tempfile.TemporaryDirectory(prefix='hla-upload-a1-restore-') as tmp:
 bare=Path(tmp)/'isolated.git'
 def run(*args):return subprocess.run(args,check=True,capture_output=True,text=True)
 run('git','init','--bare',str(bare));run('git','-C',str(bare),'fetch',str(repo),base)
 run('git','-C',str(bare),'bundle','verify',str(d/'rejected-source.bundle'))
 run('git','-C',str(bare),'fetch',str(d/'rejected-source.bundle'),'refs/heads/lane/'+aid+':refs/heads/restored')
 assert run('git','-C',str(bare),'rev-parse','restored').stdout.strip()==head
 assert not (bare/'objects/info/alternates').exists()
 restored=subprocess.check_output(['git','-C',str(bare),'show',head+':tests/test_hla1587_acceptance.py'])
 frozen_sha=hashlib.sha256(restored).hexdigest();assert frozen_sha=='38354937708ffe7f9699c836e41e65abca603b7f354c92cba5f0a482263162d3'
 run('git','-C',str(bare),'fsck','--strict')
 (d/'isolated-restore.json').write_text(json.dumps({'base_only_fetched':base,'head_restored':head,'seed_present':run('git','-C',str(bare),'rev-parse',seed).stdout.strip(),'no_alternates':True,'fsck_strict_exit':0,'frozen_acceptance_sha256':frozen_sha,'source_adopted':False},indent=2)+'\n')
(d/'REVIEW.md').write_text('''# Immutable first implementation: rejected\n\nNative Go Flash actually ran2700.2seconds and timed out124. The685added+deleted lines in seven files fit M700. The five recorded gates were green: diff-policy, fail-on-base, acceptance-on-base, frozen acceptance and Ruff. This is a truthful green-gate observation, not product completion or a reason to relabel the timeout as infrastructure. Native usage141steps confirms actual implementation work.\n\nA separate read-only source review of commita3e4709 found original-outcome defects beyond the frozen gates. No active worktree or tests were accessed for that review:\n\n1. source-row-upload.js95–108 overwrites a contradictory upstream preview target with the selected source while preserving ready. Validation provenance must be checked rather than rewritten.\n2. The client changes only its local run link. Server-rendered freshness/status/date/uploaded-as/recovery cells remain old, and local run state does not synchronize later props. Any valid update mechanism must refresh the actual row observation.\n3. Fetch rejection leaves the ready preview intact, so immediate resubmission is enabled; file input stays active during upload and is not reset afterward. JSON-parse failure clears preview, so that branch is not falsely reported as retaining readiness.\n4. describeOutcome discards superseded/missing observations and BFF qualification, possibly presenting another latest run's freshness as an unqualified landed/current result. Every receipt, including identity-mismatched/unconfirmed receipts, is assigned to the selected row's Last ingested link. Receipts must remain inspectable without becoming confirmed source-row history.\n5. Availability resolution accepts null systems/mappings/contracts reads and missing systems as available. Partial failed catalog reads must not establish verified configuration.\n6. The four added Python tests only search source strings, so they do not meaningfully exercise production helper semantics.\n\nThe integrator recorded a929-character original-scope observation before the second claim cutoff through the existing supported rejection path. The source remains rejected; no model-error fix was adopted and policy PR7 remains draft. The normal second attempt uses a different model, same R1acceptance/revision, same M700, same total two-attempt budget. There is no third retry or new-revision budget.\n\nThe bundle requires canonical HLA baseb2d0fe3. A fresh isolated bare repository fetched only that base, restored the exact source/seed/frozen test, used no alternates and passed fsck strict. Branch retirement may occur after source retention; this artifact is not a source adoption. Runtime model outcome and recorded gates are retained separately from static observations. Full Make,55visuals,sevennative specialists,architecture/product-intention,train/dev/CI/canonical feature delivery remain unobserved for this rejected source.\n''')
manifest={str(p.relative_to(d)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(d.iterdir()) if p.is_file()}
(d/'sha256.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'head':head,'worker_lines':685,'isolated_restore':True,'source_adopted':False,'retained_files':len(manifest)}),flush=True)
