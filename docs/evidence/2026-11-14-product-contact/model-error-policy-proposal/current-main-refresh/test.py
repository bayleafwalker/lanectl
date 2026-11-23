from pathlib import Path
import subprocess,os,time,json
p=Path(__file__).resolve().parent
env=dict(os.environ,XDG_RUNTIME_DIR='/run/user/1000',DBUS_SESSION_BUS_ADDRESS='unix:path=/run/user/1000/bus')
start=time.monotonic()
with (p/'full-suite-current.log').open('w') as out:
 r=subprocess.run(['uv','run','pytest','-q'],cwd='/projects/dev/_wt/lanectl-model-error-policy-20261114',env=env,stdout=out,stderr=subprocess.STDOUT)
result={'returncode':r.returncode,'elapsed_s':round(time.monotonic()-start,3),'command':'uv run pytest -q','bus_runtime':'/run/user/1000','preparation_only':True}
(p/'test-execution.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result),flush=True)
print('\n'.join((p/'full-suite-current.log').read_text().splitlines()[-15:]),flush=True)
raise SystemExit(r.returncode)
