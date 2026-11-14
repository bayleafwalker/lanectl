"""Candidate-only unit gate; fault wrappers always delegate to the actual candidate."""
import argparse, hashlib, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--checkout',required=True);p.add_argument('--wrapper',required=True);p.add_argument('--output',required=True);a=p.parse_args()
root=Path(a.checkout).resolve();out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=False)
node=None
for candidate in [shutil.which('node'),*[str(x) for x in sorted((root/'.tooling').glob('node-v20*/bin/node'))],'/projects/dev/homelab-analytics/.tooling/node-v20.20.1-linux-x64/bin/node']:
 if candidate and Path(candidate).is_file():
  v=subprocess.run([candidate,'--version'],capture_output=True,text=True)
  if v.returncode==0 and v.stdout.startswith('v20.'): node=candidate;break
if not node: raise SystemExit('Node20 missing')
helper=root/'apps/web/frontend/lib/onboarding-checklist-state.mjs';before=hashlib.sha256(helper.read_bytes()).hexdigest()
(out/'source-before.sha256').write_text(before+'\n');test=Path(__file__).with_name('onboarding-unit-contract.test.mjs').resolve()
expected=['freshness strict boundary','freshness future invalid absent','required progress ignores optional and duplicates','all core auto compact','expanded override remains full','dismissal wins over all','manual compact without core']
mutations={'freshness':expected[0],'required':expected[2],'override':expected[4],'dismissal':expected[5]}
def run(label,target):
 env=dict(os.environ,HLA_HELPER_PATH=str(target));r=subprocess.run([node,str(test)],cwd=root,env=env,capture_output=True,text=True)
 (out/(label+'.stdout')).write_text(r.stdout);(out/(label+'.stderr')).write_text(r.stderr);(out/(label+'.exit')).write_text(str(r.returncode)+'\n');return r
try:
 r=run('candidate',helper)
 assert r.returncode==0 and all(re.search(r'^ok \d+ - '+re.escape(n)+r'$',r.stdout,re.M) for n in expected)
 for line in ('# tests 7','# pass 7','# fail 0','# skipped 0','# todo 0'): assert line in r.stdout,line
 source=json.dumps(helper.as_uri())
 for kind,name in mutations.items():
  definitions={
   'freshness':"export function freshDatasetNames(rows,now){const result=real.freshDatasetNames(rows,now);return [...result,...rows.filter(r=>r.landed_at && now-new Date(r.landed_at).getTime()===7*86400000 && !result.includes(r.dataset_name)).map(r=>r.dataset_name)]}",
   'required':"export function checklistProgress(sources,fresh){return real.checklistProgress(sources.map(s=>({...s,required:true})),fresh)}",
   'override':"export function checklistView(state){return real.checklistView({...state,userExpanded:false})}",
   'dismissal':"export function checklistView(state){return real.checklistView({...state,dismissed:false})}",
  }
  names={'freshness':'freshDatasetNames','required':'checklistProgress','override':'checklistView','dismissal':'checklistView'}
  exports=['freshDatasetNames','checklistProgress','checklistView']; passthrough='\n'.join('export const '+n+'=real.'+n+';' for n in exports if n!=names[kind])
  code='import * as real from '+source+';\n'+passthrough+'\n'+definitions[kind]+'\n';path=out/(kind+'.mjs');path.write_text(code)
  r=run(kind,path)
  assert r.returncode!=0 and re.search(r'^not ok \d+ - '+re.escape(name)+r'$',r.stdout,re.M),f'{kind}: expected assertion did not fail'
  assert "failureType: 'testCodeFailure'" in r.stdout and not re.search(r'ERR_MODULE|SyntaxError|Cannot find module',r.stdout+r.stderr),f'{kind}: infrastructure failure'
 r=subprocess.run([sys.executable,'-m','pytest','-q','-p','no:cacheprovider',a.wrapper],cwd=root,capture_output=True,text=True)
 (out/'wrapper.stdout').write_text(r.stdout);(out/'wrapper.stderr').write_text(r.stderr);(out/'wrapper.exit').write_text(str(r.returncode)+'\n')
 assert r.returncode==0 and re.search(r'\b[1-9]\d* passed\b',r.stdout) and not re.search(r'\b(skipped|xfailed|xpassed)\b',r.stdout)
 # Exercise the worker's actual wrapper against each gate-generated semantic fault
 # in an owned full checkout copy. A version-only wrapper therefore cannot qualify.
 with tempfile.TemporaryDirectory(prefix='hla-worker-mutation-') as d:
  scratch=Path(d)/'checkout'
  shutil.copytree(root,scratch,symlinks=True,ignore=shutil.ignore_patterns('.git','.venv','node_modules','.next','test-results','playwright-report'))
  modules=root/'apps/web/frontend/node_modules'
  if modules.is_dir(): (scratch/'apps/web/frontend/node_modules').symlink_to(modules.resolve(),target_is_directory=True)
  target=scratch/helper.relative_to(root);sidecar=target.with_name('onboarding-checklist-state.real.mjs');shutil.copy2(helper,sidecar)
  assert hashlib.sha256(sidecar.read_bytes()).hexdigest()==before
  for kind,name in mutations.items():
   wrapper_code=(out/(kind+'.mjs')).read_text().replace(json.dumps(helper.as_uri()),json.dumps(sidecar.as_uri()))
   target.write_text(wrapper_code)
   assert hashlib.sha256(sidecar.read_bytes()).hexdigest()==before
   y=subprocess.run([sys.executable,'-m','pytest','-q','-p','no:cacheprovider',a.wrapper],cwd=scratch,capture_output=True,text=True)
   (out/('worker-'+kind+'.stdout')).write_text(y.stdout);(out/('worker-'+kind+'.stderr')).write_text(y.stderr);(out/('worker-'+kind+'.exit')).write_text(str(y.returncode)+'\n')
   text=y.stdout+y.stderr
   assert y.returncode!=0 and re.search(r'AssertionError|assert ',text) and not re.search(r'ERR_MODULE|SyntaxError|Cannot find module|ModuleNotFoundError',text), f'worker wrapper did not reject {kind} semantically'
 with tempfile.TemporaryDirectory(prefix='hla-node-shim-') as d:
  shim=Path(d)/'node';shim.write_text('#!/bin/sh\necho NODE_SHIM_REACHED >&2\nexit 91\n');shim.chmod(0o700)
  env=dict(os.environ,PATH=d+os.pathsep+os.environ.get('PATH',''),HLA_NODE=str(shim))
  x=subprocess.run([sys.executable,'-m','pytest','-q','-p','no:cacheprovider',a.wrapper],cwd=root,env=env,capture_output=True,text=True)
  (out/'wrapper-shim.stdout').write_text(x.stdout);(out/'wrapper-shim.stderr').write_text(x.stderr);(out/'wrapper-shim.exit').write_text(str(x.returncode)+'\n')
  assert x.returncode!=0 and 'NODE_SHIM_REACHED' in x.stdout+x.stderr,'wrapper did not demonstrate executing Node'
finally:
 after=hashlib.sha256(helper.read_bytes()).hexdigest();(out/'source-after.sha256').write_text(after+'\n');assert after==before,'candidate helper changed'
print('candidate helper unit and four bound fault wrappers passed; production wiring gate separately mandatory')
