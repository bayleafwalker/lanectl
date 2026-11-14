import os,pathlib,json,threading,time,subprocess,shlex
from lanectl import runner
from lanectl.config import RepoSpec
root=pathlib.Path('/tmp/lanectl-combined-prototype-20261114'); repo=root/'repo'; os.environ['LANECTL_HOME']=str(root/'home'); os.environ['LANECTL_STATE']=str(root/'state')
p=RepoSpec('synthetic',root/'canonical','main','','',repo,train_isolation='namespace'); original=runner.sandboxing.for_train
cases=['positive','exit7','timeout','noisy','quoting','stop','stop_trap','stop_ignore','lingering','pre_stop','delayed_trap']+[f'immediate{i}' for i in range(8)]
for case in cases:
 ready=repo/(case+'.ready'); done=repo/(case+'.done'); trap=repo/(case+'.trap'); unit=f'lanectl-audit-combined-{case}-20261114.service'
 class Prototype:
  def __init__(self,s): self.s=s
  def wrap_shell(self,cmd,cwd):
   argv=self.s.prefix(cwd); argv=[a if not a.startswith('RuntimeMaxSec=') else ('TimeoutStartSec=1' if case=='timeout' else 'TimeoutStartSec=12') for a in argv]
   argv+=['--unit='+unit,'-p','Type=oneshot','-p','TimeoutStopSec=2']
   if case=='pre_stop': argv+=['-p','ExecStartPre=/bin/sleep 8']
   source=dict(self.s.environment); guard=('sleep 5; ' if case=='delayed_trap' else '')+'trap "exit 125" HUP INT TERM; /bin/sh -c "$1"; rc=$?; exit "$rc"'
   payload=['/usr/bin/env','-i',*[f'{n}={source[n]}' for n in runner.sandboxing.PASS_ENV if source.get(n)],'/bin/sh','-c',guard,'lanectl-command',cmd]
   return ' '.join(shlex.quote(a) for a in argv+payload)
 runner.sandboxing.for_train=lambda **kw: Prototype(original(**kw))
 mark=f'cat /proc/self/cgroup > {shlex.quote(str(ready))}; '; donecmd=f'echo completed > {shlex.quote(str(done))}'
 cmds={'positive':mark+f'echo out; echo err >&2; {donecmd}', 'exit7':mark+'exit 7','timeout':mark+f'sleep 8; {donecmd}', 'noisy':mark+f'head -c 262144 /dev/zero | tr "\\0" x; {donecmd}', 'quoting':mark+f'printf "%s\\n" \'a $b "q"\'\nprintf second\\ line\\n; {donecmd}', 'stop':mark+f'sleep 8; {donecmd}', 'stop_trap':f"trap 'echo trapped > {trap}; exit 0' TERM; "+mark+f'sleep 8 & wait; {donecmd}', 'stop_ignore':"trap '' TERM; "+mark+f'sleep 8 & wait; {donecmd}', 'lingering':mark+f'sleep 8 & wait; {donecmd}', 'pre_stop':mark+donecmd,'delayed_trap':mark+donecmd}
 cmd=cmds.get(case,mark+f'sleep 3; {donecmd}'); results=[]; t=threading.Thread(target=lambda:results.append(runner._train_command(p,repo,cmd))); t.start()
 stop=None; observed=[]
 if case.startswith('immediate'):
  for _ in range(100):
   q=subprocess.run(['systemctl','--user','show',unit,'-p','LoadState','-p','ActiveState','-p','SubState'],capture_output=True,text=True,timeout=5)
   if 'LoadState=loaded' in q.stdout: observed.append(q.stdout); break
   if not t.is_alive(): break
   time.sleep(.002)
 elif case in ('pre_stop','delayed_trap'):
  for _ in range(200):
   q=subprocess.run(['systemctl','--user','show',unit,'-p','LoadState','-p','ActiveState','-p','SubState','-p','MainPID'],capture_output=True,text=True,timeout=5)
   if ('SubState=start-pre' if case=='pre_stop' else 'SubState=start') in q.stdout: observed.append(q.stdout); break
   if not t.is_alive(): break
   time.sleep(.01)
 elif case in ('stop','stop_trap','stop_ignore','lingering'):
  for _ in range(200):
   if ready.exists() or not t.is_alive(): break
   time.sleep(.01)
  q=subprocess.run(['systemctl','--user','show',unit,'-p','ActiveState','-p','SubState','-p','MainPID'],capture_output=True,text=True,timeout=5); observed.append(q.stdout)
 if case.startswith('immediate') or case in ('pre_stop','delayed_trap','stop','stop_trap','stop_ignore','lingering'):
  stop=subprocess.run(['systemctl','--user','stop',unit],capture_output=True,text=True,timeout=10)
 t.join(18)
 j=subprocess.run(['journalctl','--user','-u',unit,'--no-pager','-o','short-iso'],capture_output=True,text=True,timeout=10); (root/(case+'.journal')).write_text(j.stdout)
 x=results[0] if results else None
 print(json.dumps({'prototype':True,'case':case,'unit':unit,'observed':observed,'ready':ready.exists(),'done':done.exists(),'trap':trap.read_text().strip() if trap.exists() else None,'stop_rc':stop.returncode if stop else None,'stop_stderr':stop.stderr if stop else None,'thread_alive':t.is_alive(),'rc':x.returncode if x else None,'stdout_len':len(x.stdout) if x else None,'stdout':x.stdout if x and len(x.stdout)<1000 else None,'stderr':x.stderr if x else None,'journal_rc':j.returncode}),flush=True)
