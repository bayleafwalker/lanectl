from pathlib import Path
import os,glob,shlex,subprocess,json,time,hashlib
from lanectl.sandbox import for_train,transport_environment
root=Path('/projects/dev/_wt/hla1597-unit-20261115');out=Path(__file__).resolve().parent
head='57a7785c17ae76ba2169ca6af5bd4af62564a188'
assert subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()==head
assert not subprocess.check_output(['git','-C',str(root),'status','--porcelain','--untracked-files=no'],text=True).strip()
node=Path('/projects/dev/homelab-analytics/.tooling/node-v20.20.1-linux-x64/bin')
make=next(Path(x) for x in sorted(glob.glob('/nix/store/*-gnumake-*/bin/make')) if os.access(x,os.X_OK))
python=root/'.venv/bin/python';assert python.exists()
os.environ['PATH']=str(node)+os.pathsep+str(make.parent)+os.pathsep+os.environ['PATH']
os.environ['XDG_RUNTIME_DIR']='/run/user/1000';os.environ['DBUS_SESSION_BUS_ADDRESS']='unix:path=/run/user/1000/bus'
command=shlex.join([str(make),'verify-fast'])
sb=for_train(readonly=('/projects',),writable=(str(root),),timeout_s=1800,env=os.environ)
wrapped=sb.wrap_shell(command,root)
state={'head':head,'command':command,'fenced':True,'guard_completion':sb.guard_completion,'phase':'running','model_implementation_attempts':2,'product_source_changed':False,'initial_failure_retained':'initial-verify-fast.log','python_discovery':'owned .venv, no command-line PYTHON override'}
(out/'verify-state.json').write_text(json.dumps(state,indent=2)+'\n')
start=time.monotonic()
with (out/'verify-fast.log').open('w') as log:
 r=subprocess.run(wrapped,shell=True,cwd=root,env=transport_environment(),stdout=log,stderr=subprocess.STDOUT)
state.update(phase='terminal',returncode=r.returncode,elapsed_s=round(time.monotonic()-start,3),head_after=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip(),tracked_status_after=subprocess.check_output(['git','-C',str(root),'status','--porcelain','--untracked-files=no'],text=True))
(out/'verify-state.json').write_text(json.dumps(state,indent=2)+'\n')
print(json.dumps(state),flush=True)
print('\n'.join((out/'verify-fast.log').read_text().splitlines()[-25:]),flush=True)
raise SystemExit(r.returncode)
