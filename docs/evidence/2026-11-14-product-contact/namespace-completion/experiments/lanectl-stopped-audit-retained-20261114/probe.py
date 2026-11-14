import os, pathlib, subprocess, threading, time, json
from lanectl.runner import _train_command
from lanectl.config import RepoSpec
root=pathlib.Path('/tmp/lanectl-stopped-audit-retained-20261114'); repo=root/'repo'
os.environ['LANECTL_HOME']=str(root/'home'); os.environ['LANECTL_STATE']=str(root/'state')
p=RepoSpec('synthetic',root/'canonical','main','','',repo,train_isolation='namespace')
for case in ('positive','stopped'):
    ready=repo/(case+'.ready'); done=repo/(case+'.done')
    cmd=f'cat /proc/self/cgroup > {ready}; sleep {2 if case == "positive" else 60}; echo completed > {done}'
    results=[]
    t=threading.Thread(target=lambda: results.append(_train_command(p,repo,cmd)))
    t.start()
    for i in range(200):
        if ready.exists() or not t.is_alive(): break
        time.sleep(.1)
    unit=None; stop=None; journal=''
    if ready.exists():
        cg=ready.read_text().strip(); unit=cg.split('/')[-1]
        if case=='stopped' and unit.startswith('run-') and unit.endswith('.service'):
            stop=subprocess.run(['systemctl','--user','stop',unit],capture_output=True,text=True,timeout=20)
        else: stop=None
    t.join(90)
    if unit:
        j=subprocess.run(['journalctl','--user','-u',unit,'--no-pager','-o','short-iso'],capture_output=True,text=True,timeout=20); journal=j.stdout; (root/(case+'.journal')).write_text(journal)
    out={'case':case,'unit':unit,'ready':ready.exists(),'done':done.exists(),'thread_alive':t.is_alive(),'stop_rc':stop.returncode if stop else None,'stop_stderr':stop.stderr if stop else None,'result_rc':results[0].returncode if results else None,'stdout':results[0].stdout if results else None,'stderr':results[0].stderr if results else None,'journal_rc':j.returncode if unit else None}
    print(json.dumps(out),flush=True)
