from pathlib import Path
import os,glob,shlex,subprocess,json,time,hashlib
from lanectl.sandbox import for_train,transport_environment
root=Path('/projects/dev/_wt/hla1597-unit-20261115');out=Path(__file__).resolve().parent
head='57a7785c17ae76ba2169ca6af5bd4af62564a188'
assert subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()==head
b=Path('/tmp/hla1597-browser-runtime-20261115/browser-libraries.txt').read_bytes();assert hashlib.sha256(b).hexdigest()=='0511ad898d5e4a4e4f12a5b343efddb41c812be0cb6d5903c7cf61e0397cd509'
libs=b.decode().strip();assert all(Path(x).is_dir() for x in libs.split(':'))
make=next(Path(x) for x in sorted(glob.glob('/nix/store/*-gnumake-*/bin/make')) if os.access(x,os.X_OK))
os.environ.update(PATH='/projects/dev/homelab-analytics/.tooling/node-v20.20.1-linux-x64/bin'+os.pathsep+str(make.parent)+os.pathsep+os.environ['PATH'],XDG_RUNTIME_DIR='/run/user/1000',DBUS_SESSION_BUS_ADDRESS='unix:path=/run/user/1000/bus')
command='export LD_LIBRARY_PATH='+shlex.quote(libs)+'; '+shlex.join([str(make),'web-ui-test','helm-lint'])
sb=for_train(readonly=('/projects',),writable=(str(root),),timeout_s=900,env=os.environ)
state={'head':head,'phase':'running','targets':['web-ui-test','helm-lint'],'runtime_list_sha256':hashlib.sha256(b).hexdigest(),'tests_baselines_tolerances_changed':False}
(out/'visual-state.json').write_text(json.dumps(state,indent=2)+'\n');start=time.monotonic()
with (out/'visual.log').open('w') as log:r=subprocess.run(sb.wrap_shell(command,root),shell=True,cwd=root,env=transport_environment(),stdout=log,stderr=subprocess.STDOUT)
state.update(phase='terminal',returncode=r.returncode,elapsed_s=round(time.monotonic()-start,3),tracked_status_after=subprocess.check_output(['git','-C',str(root),'status','--porcelain','--untracked-files=no'],text=True))
(out/'visual-state.json').write_text(json.dumps(state,indent=2)+'\n')
print(json.dumps(state),flush=True);print('\n'.join((out/'visual.log').read_text().splitlines()[-20:]),flush=True)
raise SystemExit(r.returncode)
