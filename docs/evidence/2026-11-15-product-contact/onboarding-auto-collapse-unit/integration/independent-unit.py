from pathlib import Path
import hashlib,json,os,re,shlex,subprocess
from lanectl.sandbox import for_train,transport_environment
root=Path('/projects/dev/_wt/hla1597-unit-20261115');out=Path(__file__).resolve().parent
node='/projects/dev/homelab-analytics/.tooling/node-v20.20.1-linux-x64/bin/node'
suite=root/'apps/web/frontend/unit/onboarding-auto-collapse.test.cjs';preload=Path('/tmp/hla1597-unit-20261115/mutant-preload.cjs')
expectedhead='57a7785c17ae76ba2169ca6af5bd4af62564a188'
assert subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()==expectedhead
paths=[suite,root/'apps/web/frontend/components/onboarding-checklist.js',root/'apps/web/frontend/lib/onboarding-sources.js']
before={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
os.environ['XDG_RUNTIME_DIR']='/run/user/1000';os.environ['DBUS_SESSION_BUS_ADDRESS']='unix:path=/run/user/1000/bus'
results={}
for label,args in [('green',[node,'--test',str(suite)]),('red',[node,'-r',str(preload),'--test',str(suite)])]:
 sb=for_train(readonly=('/projects',),writable=(str(root),),timeout_s=60,env=os.environ)
 r=subprocess.run(sb.wrap_shell(shlex.join(args),root/'apps/web/frontend'),shell=True,cwd=root,env=transport_environment(),capture_output=True,text=True)
 text=r.stdout+r.stderr;(out/('independent-'+label+'.log')).write_text(text)
 results[label]={'returncode':r.returncode,'tests':int(re.search(r'^# tests (\d+)$',text,re.M)[1]),'passed':int(re.search(r'^# pass (\d+)$',text,re.M)[1]),'failed':int(re.search(r'^# fail (\d+)$',text,re.M)[1]),'skipped':int(re.search(r'^# skipped (\d+)$',text,re.M)[1]),'failed_names':re.findall(r'^not ok \d+ - (.+)$',text,re.M)}
assert results['green']=={'returncode':0,'tests':10,'passed':10,'failed':0,'skipped':0,'failed_names':[]},results
assert results['red']=={'returncode':1,'tests':10,'passed':7,'failed':3,'skipped':0,'failed_names':['both cores -> compact 2/5','both cores + optional -> compact 3/5','all five -> compact 5/5']},results
assert before=={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
proof={'head':expectedhead,'results':results,'source_hashes_before_after_equal':before,'mutant':'externalModule.prototype._compile replaces ONLY compiledautomaticcollapsebranch; noondiskproductmutation','fenced_completion':True}
(out/'independent-unit-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof,indent=2),flush=True)
