import json, os, pathlib, shutil, subprocess, time
from lanectl.sandbox import from_lane, transport_environment
out=pathlib.Path('/tmp/hla1597-unit-20261115')
wt=pathlib.Path('/projects/dev/_wt/hla1597-unit-20261115')
os.environ['XDG_RUNTIME_DIR']='/run/user/1000'
os.environ['DBUS_SESSION_BUS_ADDRESS']='unix:path=/run/user/1000/bus'
os.environ['PATH']='/projects/dev/homelab-analytics/.tooling/node-v20.20.1-linux-x64/bin:'+os.environ['PATH']
sb=from_lane({'mode':'systemd-run','readonly':['/projects']},(str(wt),),2820,attempt_id='interactive-hla1597-unit-a1')
cmd=[*sb.prefix(wt),shutil.which('claude'),'-p','--model','claude-sonnet-5-5','--output-format','json','--restricted','--strict-mcp-config','--permission-mode','acceptEdits','--tools','Read,Grep,Glob,Bash,Edit,Write','--allowedTools','Read','Grep','Glob','Bash','Edit','Write','--disallowedTools','Read(**/error.log)','--permission-prompts','none']
state={'unit':sb.unit,'model':'claude-sonnet-5-5','attempt':1,'command':cmd,'started_at':time.time()}
(out/'process.json').write_text(json.dumps(state,indent=2))
with (out/'native.json').open('w') as stdout,(out/'native.stderr').open('w') as stderr:
 p=subprocess.run(cmd,input=(out/'prompt.txt').read_text(),text=True,stdout=stdout,stderr=stderr,env=transport_environment())
(out/'native.exit').write_text(str(p.returncode)+'\n')
state.update(exit=p.returncode,ended_at=time.time())
try:
 result=json.loads((out/'native.json').read_text());state.update(modelUsage=result.get('modelUsage'),native_subtype=result.get('subtype'),is_error=result.get('is_error'))
except (ValueError,OSError): pass
(out/'process.json').write_text(json.dumps(state,indent=2))
raise SystemExit(p.returncode)
