from pathlib import Path
import os, json, dataclasses, subprocess, threading, time, shlex, hashlib
from importlib.metadata import version
from lanectl import runner, sandbox
from lanectl.config import RepoSpec
root=Path('/tmp/lanectl-v012-installed-probe');root.mkdir(exist_ok=True)
for name in ('canonical','checkout','home','state'):(root/name).mkdir(exist_ok=True)
os.environ['LANECTL_HOME']=str(root/'home');os.environ['LANECTL_STATE']=str(root/'state')
assert version('lanectl')=='0.2.12'
assert str(Path(runner.__file__)).startswith('/home/bayleaf/.local/share/uv/tools/lanectl/')
repo=RepoSpec('synthetic',root/'canonical','main','','',root/'worktrees',train_isolation='namespace')
original=sandbox.for_train;unit='lanectl-v012-installed-stop-probe.service'
sandbox.for_train=lambda **kw:dataclasses.replace(original(**kw),unit=unit)
ready=root/'ready';done=root/'done';stop=[]
def cancel():
 deadline=time.monotonic()+10
 while not ready.exists() and time.monotonic()<deadline:time.sleep(.01)
 if ready.exists():stop.append(subprocess.run(['systemctl','--user','stop',unit],capture_output=True,timeout=20).returncode)
t=threading.Thread(target=cancel);t.start()
cmd='trap "exit 0" TERM; touch '+shlex.quote(str(ready))+'; sleep 30 & wait; touch '+shlex.quote(str(done))
r=runner._train_command(repo,root/'checkout',cmd);t.join(25)
assert not t.is_alive() and stop==[0] and r.returncode!=0 and not done.exists(),(stop,r)
sandbox.for_train=original
positive=runner._train_command(repo,root/'checkout',"printf installed-completion-ok")
assert (positive.returncode,positive.stdout)==(0,'installed-completion-ok'),positive
source=Path('/projects/dev/lanectl/src/lanectl');installed=Path(runner.__file__).parent
files=list(source.rglob('*.py'))
assert all(p.read_bytes()==(installed/p.relative_to(source)).read_bytes() for p in files)
proof={'distribution':version('lanectl'),'release_commit':subprocess.check_output(['git','-C','/projects/dev/lanectl','rev-parse','v0.2.12'],text=True).strip(),'runtime_files_equal':len(files),'installed_path':str(installed),'stop_acknowledged':stop[0],'stopped_check_exit':r.returncode,'incomplete_marker_absent':not done.exists(),'positive_exit':positive.returncode,'positive_stdout':positive.stdout,'systemd_version':'262','scope':'namespace completion; no credential, grant, policy or strict receipt changes'}
(root/'result.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof))
