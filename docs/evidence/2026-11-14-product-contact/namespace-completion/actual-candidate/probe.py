import os,pathlib,json,threading,time,subprocess,shlex,dataclasses,hashlib
from lanectl import runner,sandbox
from lanectl.config import RepoSpec
root=pathlib.Path('/tmp/lanectl-candidate-7842494-20261114'); repo=root/'repo'; os.environ['LANECTL_HOME']=str(root/'home'); os.environ['LANECTL_STATE']=str(root/'state')
p=RepoSpec('synthetic',root/'canonical','main','','',repo,train_isolation='namespace'); original=runner.sandboxing.for_train
for case in ['positive','exit7','inner_timeout','noisy','quotes','ignore_stop']:
 ready=repo/(case+'.ready'); done=repo/(case+'.done'); child=repo/(case+'.child'); unit=f'lanectl-audit-candidate-{case}-7842494.service'
 runner.sandboxing.for_train=lambda **kw: dataclasses.replace(original(**kw),unit=unit)
 mark=f'cat /proc/self/cgroup > {shlex.quote(str(ready))}; '; donecmd=f'echo completed > {shlex.quote(str(done))}'
 quotes="printf '%s\\n' 'a $b \"quoted\"'\nprintf '%s\\n' 'second line'\nprintf '%s\\n' \"literal \\\$HOME\"\n"+donecmd
 cmds={'positive':mark+f'echo out; echo err >&2; {donecmd}', 'exit7':mark+'exit 7','inner_timeout':mark+'timeout 1s sleep 20', 'noisy':mark+f'head -c 262144 /dev/zero | tr "\\0" x; {donecmd}', 'quotes':quotes,'ignore_stop':"trap '' TERM; "+mark+f'sleep 45 & echo $! > {child}; wait; {donecmd}'}
 results=[]; t=threading.Thread(target=lambda:results.append(runner._train_command(p,repo,cmds[case]))); t.start(); stop=None; state=None; pids=[]; elapsed=None; pid_alive=[]
 if case=='ignore_stop':
  for _ in range(300):
   if ready.exists() and child.exists(): break
   if not t.is_alive(): break
   time.sleep(.02)
  q=subprocess.run(['systemctl','--user','show',unit,'-p','ActiveState','-p','SubState','-p','MainPID','-p','ControlGroup','-p','TimeoutStopUSec'],capture_output=True,text=True); state=q.stdout
  cg=next((ln.split('=',1)[1] for ln in state.splitlines() if ln.startswith('ControlGroup=')),None)
  if cg:
   procs=pathlib.Path('/sys/fs/cgroup')/cg.lstrip('/')/'cgroup.procs'
   if procs.exists(): pids=[int(z) for z in procs.read_text().splitlines()]
  before=time.monotonic(); stop=subprocess.run(['systemctl','--user','stop',unit],capture_output=True,text=True,timeout=25); elapsed=time.monotonic()-before
  pid_alive=[n for n in pids if pathlib.Path('/proc',str(n)).exists()]
 t.join(25)
 j=subprocess.run(['journalctl','--user','-u',unit,'--no-pager','-o','short-iso'],capture_output=True,text=True); (root/(case+'.journal')).write_text(j.stdout)
 x=results[0] if results else None
 print(json.dumps({'source':runner.__file__,'source_sandbox':sandbox.__file__,'sandbox_sha256':hashlib.sha256(pathlib.Path(sandbox.__file__).read_bytes()).hexdigest(),'case':case,'unit':unit,'observed':state,'cgroup_pids_before':pids,'pids_alive_after_stop':pid_alive,'stop_rc':stop.returncode if stop else None,'stop_elapsed_s':elapsed,'ready':ready.exists(),'done':done.exists(),'thread_alive':t.is_alive(),'rc':x.returncode if x else None,'stdout_len':len(x.stdout) if x else None,'stdout':x.stdout if x and len(x.stdout)<1000 else None,'stderr':x.stderr if x else None,'journal_rc':j.returncode,'expected_quotes': 'a $b "quoted"\nsecond line\nliteral $HOME\n' if case=='quotes' else None,'quotes_match':x.stdout == 'a $b "quoted"\nsecond line\nliteral $HOME\n' if case=='quotes' and x else None}),flush=True)
