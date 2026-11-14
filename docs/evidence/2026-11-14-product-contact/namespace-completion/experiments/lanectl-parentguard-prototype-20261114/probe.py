import os,pathlib,json,threading,time,subprocess,shlex
from lanectl import runner
from lanectl.config import RepoSpec
root=pathlib.Path('/tmp/lanectl-parentguard-prototype-20261114'); repo=root/'repo'
os.environ['LANECTL_HOME']=str(root/'home'); os.environ['LANECTL_STATE']=str(root/'state')
p=RepoSpec('synthetic',root/'canonical','main','','',repo,train_isolation='namespace'); original=runner.sandboxing.for_train
class Prototype:
 def __init__(self,sb,runtime): self.sb,self.runtime=sb,runtime
 def wrap_shell(self,cmd,cwd):
  argv=self.sb.prefix(cwd)
  if self.runtime: argv=[a if not a.startswith('RuntimeMaxSec=') else f'RuntimeMaxSec={self.runtime}' for a in argv]
  source=dict(self.sb.environment)
  payload=['/usr/bin/env','-i',*[f'{n}={source[n]}' for n in runner.sandboxing.PASS_ENV if source.get(n)],'/bin/sh','-c','trap "exit 125" HUP INT TERM; /bin/sh -c "$1"; rc=$?; exit "$rc"','lanectl-command',cmd]
  return ' '.join(shlex.quote(a) for a in argv+payload)
for case in ('positive','exit7','inner_timeout','stop','stop_trap','runtime','noisy','exec_exit7','direct_exit0'):
 ready=repo/(case+'.ready'); done=repo/(case+'.done'); trap=repo/(case+'.trap')
 runner.sandboxing.for_train=lambda **kw: Prototype(original(**kw),1 if case=='runtime' else None)
 mark=f'cat /proc/self/cgroup > {shlex.quote(str(ready))}; '
 cmds={'positive':mark+f'echo out; echo err >&2; echo completed > {done}', 'exit7':mark+'exit 7', 'inner_timeout':mark+'timeout 1s sleep 20', 'stop':mark+f'sleep 20; echo completed > {done}', 'stop_trap':f"trap 'echo trapped > {trap}; exit 0' TERM; "+mark+f'sleep 20 & wait; echo completed > {done}', 'runtime':mark+f'sleep 20; echo completed > {done}', 'noisy':mark+f'head -c 262144 /dev/zero | tr "\\0" x; echo completed > {done}', 'exec_exit7':mark+"exec /bin/sh -c 'exit 7'", 'direct_exit0':mark+'exit 0'}
 results=[]; t=threading.Thread(target=lambda:results.append(runner._train_command(p,repo,cmds[case]))); t.start()
 for _ in range(150):
  if ready.exists() or not t.is_alive(): break
  time.sleep(.02)
 cg=ready.read_text().strip() if ready.exists() else None; unit=cg.split('/')[-1] if cg else None
 state=None; stop=None; jrc=None
 if unit:
  state=subprocess.run(['systemctl','--user','show',unit,'-p','ActiveState','-p','SubState','-p','Type','-p','MainPID','-p','ControlGroup','-p','RuntimeMaxUSec'],capture_output=True,text=True,timeout=10).stdout
  if case in ('stop','stop_trap') and unit.startswith('run-') and unit.endswith('.service'):
   stop=subprocess.run(['systemctl','--user','stop',unit],capture_output=True,text=True,timeout=10)
 t.join(15)
 if unit:
  j=subprocess.run(['journalctl','--user','-u',unit,'--no-pager','-o','short-iso'],capture_output=True,text=True,timeout=10); jrc=j.returncode; (root/(case+'.journal')).write_text(j.stdout)
 x=results[0] if results else None
 out={'prototype':True,'case':case,'unit':unit,'cgroup':cg,'state_during':state,'ready':ready.exists(),'done':done.exists(),'trap':trap.read_text().strip() if trap.exists() else None,'stop_rc':stop.returncode if stop else None,'thread_alive':t.is_alive(),'returncode':x.returncode if x else None,'stdout_len':len(x.stdout) if x else None,'stdout':x.stdout if x and len(x.stdout)<1024 else None,'stderr':x.stderr if x else None,'journal_rc':jrc}
 print(json.dumps(out),flush=True)
