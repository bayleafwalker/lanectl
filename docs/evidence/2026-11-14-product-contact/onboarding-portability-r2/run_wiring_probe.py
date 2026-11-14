"""Candidate-only real-component mutant; no candidate checkout edits."""
import argparse, hashlib, json, os, shutil, subprocess, sys, tempfile, xml.etree.ElementTree as ET
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--checkout',required=True);p.add_argument('--baseline-evidence',required=True);p.add_argument('--output',required=True);a=p.parse_args()
root=Path(a.checkout).resolve();out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=False)
def cmd(args,cwd=root): return subprocess.check_output(args,cwd=cwd,text=True).strip()
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
sha=cmd(['git','rev-parse','HEAD']);assert len(sha)==40
assert not cmd(['git','status','--porcelain','--untracked-files=all']),'candidate must be clean'
rel=Path('apps/web/frontend/lib/onboarding-checklist-state.mjs');helper=root/rel;before=digest(helper)
acceptance=Path(__file__).with_name('test_onboarding_expand_acceptance.py');candidate_test=root/'tests/test_onboarding_expand_acceptance.py'
assert candidate_test.is_file() and digest(candidate_test)==digest(acceptance),'candidate frozen test bytes mismatch'
modules=root/'apps/web/frontend/node_modules'
# Bind all baseline tracked bytes, modes and symlinks to this exact checkout
# before allocating a scratch worktree or launching Next.
baseline=Path(a.baseline_evidence).resolve();expected=json.loads((baseline/'source-fingerprint.json').read_text())
tracked=subprocess.check_output(['git','ls-files','-z'],cwd=root).split(b'\0');actual={}
for raw in tracked:
 if not raw: continue
 f=root/os.fsdecode(raw);key=str(f.relative_to(root))
 actual[key]=['link',os.readlink(f)] if f.is_symlink() else [f.stat().st_mode,digest(f)]
assert actual==expected,'baseline fingerprint does not match exact candidate checkout'
values=json.loads((baseline/'browser.stdout').read_text());suite=ET.parse(baseline/'junit.xml').getroot()
assert len(values)==16 and all(x.get('ok') is True for x in values.values()) and len(list(suite.iter('testcase')))==16 and not any(list(suite.iter(t)) for t in ('skipped','failure','error')),'baseline is not complete green'
assert (baseline/'browser.exit').read_text().strip()=='0' and (baseline/'source-invariance.txt').read_text().strip()=='tracked source unchanged' and (baseline/'outer-invariance.txt').read_text().strip()=='tracked source unchanged' and (baseline/'aggregate-errors.txt').read_text().strip()=='none','baseline invariance or browser evidence invalid'
(out/'baseline-match.json').write_text(json.dumps({'source_sha':sha,'tracked_files':len(actual),'fingerprint_sha256':digest(baseline/'source-fingerprint.json')},indent=2)+'\n')
record={'sha':sha,'original_helper_sha256':before,'acceptance_sha256':digest(acceptance)};(out/'identity.json').write_text(json.dumps(record,indent=2)+'\n')
with tempfile.TemporaryDirectory(prefix='hla-wiring-') as temp:
 scratch=Path(temp)/'checkout';created=False
 try:
  subprocess.run(['git','worktree','add','--detach',str(scratch),sha],cwd=root,check=True,capture_output=True,text=True);created=True
  source=scratch/rel; assert digest(source)==before
  sidecar=source.with_name('onboarding-checklist-state.real.mjs');shutil.copy2(source,sidecar);assert digest(sidecar)==before
  source.write_text('import * as real from "./onboarding-checklist-state.real.mjs";\nexport const freshDatasetNames=real.freshDatasetNames;\nexport const checklistProgress=real.checklistProgress;\nexport function checklistView(state){return real.checklistView({...state,userExpanded:false})}\n')
  if (modules/'next/package.json').is_file(): (scratch/'apps/web/frontend/node_modules').symlink_to(modules.resolve(),target_is_directory=True)
  env=dict(os.environ,HLA_ONBOARDING_EVIDENCE=str(out/'mutant-evidence'))
  with (out/'mutant-cli.stdout').open('w') as stdout,(out/'mutant-cli.stderr').open('w') as stderr:
   run=subprocess.run([sys.executable,'tests/test_onboarding_expand_acceptance.py'],cwd=scratch,env=env,stdout=stdout,stderr=stderr)
  (out/'mutant-cli.exit').write_text(str(run.returncode)+'\n');assert run.returncode!=0,'wiring mutant unexpectedly passed'
  gate=subprocess.run([sys.executable,str(Path(__file__).with_name('qualify_wiring.py')),'--candidate',str(Path(a.baseline_evidence).resolve()),'--mutant',str(out/'mutant-evidence')],capture_output=True,text=True)
  (out/'wiring-gate.stdout').write_text(gate.stdout);(out/'wiring-gate.stderr').write_text(gate.stderr);(out/'wiring-gate.exit').write_text(str(gate.returncode)+'\n');assert gate.returncode==0,'wiring gate failed; see logs'
 finally:
  errors=[]
  if created:
   removed=subprocess.run(['git','worktree','remove','--force',str(scratch)],cwd=root,capture_output=True,text=True)
   if removed.returncode or scratch.exists(): errors.append('owned scratch worktree cleanup failed')
  if digest(helper)!=before: errors.append('candidate helper changed')
  if cmd(['git','rev-parse','HEAD'])!=sha or cmd(['git','status','--porcelain','--untracked-files=all']): errors.append('candidate checkout changed')
  (out/'cleanup.txt').write_text('\n'.join(errors)+'\n' if errors else 'owned scratch absent; candidate source invariant\n')
  if errors: raise AssertionError('; '.join(errors))
print('candidate-derived wiring mutant verified')
