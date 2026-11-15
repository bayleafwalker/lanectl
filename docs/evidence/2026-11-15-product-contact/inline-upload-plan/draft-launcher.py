from pathlib import Path
from dataclasses import replace
import json
import os
import shutil
import subprocess
import time
from lanectl.config import load_lane
from lanectl.sandbox import from_lane

root = Path('/tmp/hla-inline-upload-plan-20261115')
assert not root.exists()
root.mkdir()
checkout = root / 'checkout'
source = Path('/projects/dev/homelab-analytics')
base = 'b2d0fe393ac0971e906cce275e91f45e94422593'
subprocess.run(['git','clone','-q','--shared','--no-checkout',str(source),str(checkout)],check=True)
subprocess.run(['git','-C',str(checkout),'checkout','-q','--detach',base],check=True)
subprocess.run(['git','-C',str(checkout),'remote','remove','origin'],check=True)
prompt = Path('/tmp/hla-inline-upload-plan-20261115-prompt.txt').read_text()
(root / 'prompt.txt').write_text(prompt)
runtime = root / 'runtime'
runtime.mkdir()
sb = from_lane(load_lane('implement').sandbox, (str(checkout),str(runtime)), 1260,
               attempt_id='plan-hla-inline-upload-20261115')
sb = replace(sb, readonly=(*sb.readonly,str(source),'/projects/dev/lanectl'))
args = [shutil.which('claude'),'-p','--model','claude-opus-5-5','--output-format','json',
        '--restricted','--strict-mcp-config','--tools','Read,Grep,Glob',
        '--allowedTools','Read,Grep,Glob','--permission-prompts','none']
started = time.monotonic()
(root / 'live.json').write_text(json.dumps({'unit':sb.unit,'model':'claude-opus-5-5','base':base,'purpose':'read-only planning HLA1587'})+'\n')
try:
    result = subprocess.run(sb.prefix(checkout)+args, input=prompt, text=True,
                            capture_output=True, cwd=checkout, timeout=1290)
except BaseException:
    sb.cancel()
    raise
(root / 'native.json').write_text(result.stdout)
(root / 'native.stderr').write_text(result.stderr)
dirty = subprocess.run(['git','-C',str(checkout),'status','--porcelain'],capture_output=True,text=True,check=True).stdout
meta = {'requested_model':'claude-opus-5-5','tools':['Read','Grep','Glob'],
        'elapsed_seconds':round(time.monotonic()-started,3),'exit_code':result.returncode,
        'source_sha':base,'unit':sb.unit,'tracked_and_untracked_clean':not dirty}
(root / 'execution.json').write_text(json.dumps(meta,indent=2)+'\n')
assert result.returncode == 0 and not dirty, meta
native = json.loads(result.stdout)
assert not native.get('is_error') and isinstance(native.get('result'),str) and native['result'].strip()
(root / 'plan.md').write_text(native['result']+'\n')
print(json.dumps(meta),flush=True)
