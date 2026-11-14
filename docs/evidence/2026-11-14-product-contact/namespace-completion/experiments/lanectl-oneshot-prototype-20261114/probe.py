import os,pathlib,json,threading,time,subprocess
from lanectl import runner
from lanectl.config import RepoSpec
root=pathlib.Path('/tmp/lanectl-oneshot-prototype-20261114'); repo=root/'repo'
os.environ['LANECTL_HOME']=str(root/'home'); os.environ['LANECTL_STATE']=str(root/'state')
p=RepoSpec('synthetic',root/'canonical','main','','',repo,train_isolation='namespace')
original=runner.sandboxing.for_train
class Prototype:
 def __init__(self,sb,deadline): self.sb,self.deadline=sb,deadline
 def wrap_shell(self,cmd,cwd):
  import shlex
  argv=self.sb.prefix(cwd)
  argv=[a if not a.startswith('RuntimeMaxSec=') else f'TimeoutStartSec={self.deadline}' for a in argv]
  argv += ['-p','Type=oneshot']
  source=dict(self.sb.environment)
  payload=['/usr/bin/env','-i',*[f'{n}={source[n]}' for n in runner.sandboxing.PASS_ENV if source.get(n)],'/bin/sh','-c',cmd]
  return ' '.join(shlex.quote(a) for a in argv+payload)
for case in ('positive','exit7','missing_exec','inner_timeout','start_deadline','stop','stop_trap'):
 ready=repo/(case+'.ready'); done=repo/(case+'.done')
 deadline=1 if case=='start_deadline' else 30
 runner.sandboxing.for_train=lambda **kw: Prototype(original(**kw),deadline)
 mark=f'cat /proc/self/cgroup > {ready}; '
 cmds={'positive':mark+f'echo out; echo err >&2; echo completed > {done}', 'exit7':mark+'exit 7', 'missing_exec':mark+'exec /nonexistent/lanectl-synthetic-missing', 'inner_timeout':mark+'timeout 1s sleep 20', 'start_deadline':mark+f'sleep 20; echo completed > {done}', 'stop':mark+f'sleep 20; echo completed > {done}', 'stop_trap':"trap 'exit 0' TERM; "+mark+f'sleep 20 & wait; echo completed > {done}'}
 results=[]; t=threading.Thread(target=lambda:results.append(runner._train_command(p,repo,cmds[case]))); t.start()
 for _ in range(150):
  if ready.exists() or not t.is_alive(): break
  time.sleep(.02)
 unit=ready.read_text().strip().split('/')[-1] if ready.exists() else None
 state=None; stop=None; jrc=None
 if unit:
  state=subprocess.run(['systemctl','--user','show',unit,'-p','ActiveState','-p','SubState','-p','Type','-p','TimeoutStartUSec'],capture_output=True,text=True,timeout=10).stdout
  if case in ('stop','stop_trap') and unit.startswith('run-') and unit.endswith('.service'):
   stop=subprocess.run(['systemctl','--user','stop',unit],capture_output=True,text=True,timeout=10)
 t.join(15)
 if unit:
  j=subprocess.run(['journalctl','--user','-u',unit,'--no-pager','-o','short-iso'],capture_output=True,text=True,timeout=10); jrc=j.returncode; (root/(case+'.journal')).write_text(j.stdout)
 print(json.dumps({'prototype':True,'case':case,'properties':{'Type':'oneshot','TimeoutStartSec':deadline,'RuntimeMaxSec':'omitted'},'unit':unit,'state_during':state,'ready':ready.exists(),'done':done.exists(),'stop_rc':stop.returncode if stop else None,'stop_stderr':stop.stderr if stop else None,'thread_alive':t.is_alive(),'returncode':results[0].returncode if results else None,'stdout':results[0].stdout if results else None,'stderr':results[0].stderr if results else None,'journal_rc':jrc}),flush=True)
