from pathlib import Path
from dataclasses import replace
import json, shutil, subprocess, time
from lanectl.config import load_lane
from lanectl.sandbox import from_lane

root=Path('/tmp/hla-inline-upload-plan-followup-20261115')
assert not root.exists()
root.mkdir()
checkout=root/'checkout'
base='b2d0fe393ac0971e906cce275e91f45e94422593'
subprocess.run(['git','clone','-q','--shared','--no-checkout','/projects/dev/homelab-analytics',str(checkout)],check=True)
subprocess.run(['git','-C',str(checkout),'checkout','-q','--detach',base],check=True)
subprocess.run(['git','-C',str(checkout),'remote','remove','origin'],check=True)
shutil.copy2('/tmp/hla-inline-upload-plan-followup-20261115-prompt.txt',root/'prompt.txt')
runtime=root/'runtime';runtime.mkdir()
sb=from_lane(load_lane('implement').sandbox,(str(checkout),str(runtime)),1260,attempt_id='plan-hla-inline-upload-followup-20261115')
sb=replace(sb,readonly=(*sb.readonly,'/projects/dev/homelab-analytics','/projects/dev/lanectl'))
prefix=[a for a in sb.prefix(checkout) if a!='--pipe']
prefix += ['-p','StandardInput=file:'+str(root/'prompt.txt'),'-p','StandardOutput=append:'+str(root/'native.json'),'-p','StandardError=append:'+str(root/'native.stderr')]
args=[shutil.which('claude'),'-p','--model','claude-opus-5-5','--output-format','json','--restricted','--strict-mcp-config','--tools','Read,Grep,Glob','--allowedTools','Read,Grep,Glob','--permission-prompts','none']
(root/'live.json').write_text(json.dumps({'unit':sb.unit,'model':'claude-opus-5-5','base':base,'native_stdio':'owned files managed by systemd; survives supervisor loss'})+'\n')
start=time.monotonic()
try:result=subprocess.run(prefix+args,cwd=checkout,capture_output=True,text=True,timeout=1290)
except BaseException:
 sb.cancel();raise
(root/'supervisor.stdout').write_text(result.stdout)
(root/'supervisor.stderr').write_text(result.stderr)
dirty=subprocess.run(['git','-C',str(checkout),'status','--porcelain'],capture_output=True,text=True,check=True).stdout
meta={'model':'claude-opus-5-5','source_sha':base,'source_clean':not dirty,'exit_code':result.returncode,'elapsed_s':round(time.monotonic()-start,3),'unit':sb.unit}
(root/'execution.json').write_text(json.dumps(meta,indent=2)+'\n')
assert result.returncode==0 and not dirty,meta
native=json.loads((root/'native.json').read_text())
assert not native.get('is_error') and native.get('result')
(root/'plan.md').write_text(native['result']+'\n')
print(json.dumps(meta),flush=True)
