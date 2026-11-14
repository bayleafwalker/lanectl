from pathlib import Path
import importlib.util, os, re, socket, subprocess, time, uuid
from contextlib import closing
p=Path('/tmp/hla-attention-ui-spec/files/tests/test_attention_current_ui_acceptance.py'); spec=importlib.util.spec_from_file_location('acceptance',p); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
expr=re.search(r'const groups=(.*);\nconsole\.log',m.BROWSER).group(1)
with closing(socket.socket()) as sock: sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
name='hla-ui-group-control-'+uuid.uuid4().hex[:12]; cid=None
try:
 cid=subprocess.check_output(['docker','run','-d','--name',name,'--network','host','--ipc=host','-v','/tmp/hla-attention-ui-spec/base/apps/web/frontend/node_modules:/opt/node_modules:ro',m.IMAGE,'node','/opt/node_modules/playwright/cli.js','run-server','--host','127.0.0.1','--port',str(port)],text=True).strip()
 for _ in range(40):
  logs=subprocess.run(['docker','logs',cid],capture_output=True,text=True)
  if 'Listening on' in logs.stdout+logs.stderr: break
  time.sleep(.5)
 else: raise RuntimeError('browser not ready: '+logs.stdout+logs.stderr)
 script=Path('/tmp/hla-attention-ui-spec/check-disjoint.cjs')
 script.write_text("const {chromium}=require('playwright');(async()=>{let b=await chromium.connect(process.argv[2]);let p=await b.newPage();for (const html of [\"<main><li><dl><dt>Same row</dt></dl></li></main>\",\"<main><li><dl><dt>Same row</dt></dl></li><li><dl><dt>Same row</dt></dl></li></main>\"]) { await p.setContent(html); let groups="+expr+"; console.log(JSON.stringify(groups)); }await b.close()})().catch(e=>{console.error(e);process.exit(1)})")
 env=dict(os.environ,NODE_PATH='/tmp/hla-attention-ui-spec/base/apps/web/frontend/node_modules',PATH=m.NODE+':'+os.environ['PATH'])
 result=subprocess.check_output(['node',str(script),f'ws://127.0.0.1:{port}/'],env=env,text=True).splitlines()
 import json
 one,two=map(json.loads,result); assert len(one)==1 and len(two)==2 and one[0]==two[0]==two[1],(one,two)
 print('actual browser group expression: nested single row -> 1; two identical sibling rows -> 2')
finally:
 if cid:
  subprocess.run(['docker','rm','-f',cid],capture_output=True)
  inv=subprocess.run(['docker','ps','-a','--no-trunc','--format','{{.ID}}'],capture_output=True,text=True)
  assert inv.returncode==0 and cid not in inv.stdout.splitlines(), 'owned browser remains'
  print('owned browser absent')
