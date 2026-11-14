import json, os, subprocess, tempfile, uuid
from pathlib import Path
from tests.test_attention_record_boundary_acceptance import Lab, IMAGE, port
import tests.test_attention_record_boundary_acceptance as acceptance
with tempfile.TemporaryDirectory(prefix='hla-browser-preflight-') as d:
    d=Path(d)
    with Lab(d) as lab:
        name='hla-boundary-preflight-'+uuid.uuid4().hex[:12]; cidfile=d/'cid'; browser_port=port()
        try:
            p=subprocess.run(['docker','run','-d','--cidfile',str(cidfile),'--name',name,'--network','host','--ipc=host','-v',str(acceptance.PINNED_MODULES)+':/opt/node_modules:ro',IMAGE,'node','/opt/node_modules/playwright/cli.js','run-server','--host','127.0.0.1','--port',str(browser_port)],capture_output=True,text=True,timeout=45)
            assert p.returncode==0,(p.stdout,p.stderr)
            code='''const {chromium}=require('playwright'); (async()=>{let b=await chromium.connect(process.argv[1]);try {let p=await b.newPage();let r=await p.goto(process.argv[2]);if(r.status()!=200)throw Error('bad');console.log('browser reached genuine Next transport');} finally {await b.close()}})().catch(e=>{console.error(e);process.exit(1)});'''
            import time
            for i in range(40):
                logs=subprocess.run(['docker','logs',p.stdout.strip()],capture_output=True,text=True)
                if 'Listening on' in logs.stdout+logs.stderr: break
                time.sleep(.5)
            else: raise RuntimeError('browser failed to start')
            env=dict(os.environ,NODE_PATH=str(acceptance.PINNED_MODULES)); result=subprocess.run(['node','-e',code,f'ws://127.0.0.1:{browser_port}/',lab.url('/acceptance-infra')],env=env,capture_output=True,text=True,timeout=30); print(result.stdout); assert result.returncode==0,result.stderr
        finally:
            cid=cidfile.read_text().strip() if cidfile.exists() else None
            if cid: subprocess.run(['docker','rm','-f',cid],check=True,capture_output=True)
            ids=subprocess.run(['docker','ps','-a','--no-trunc','--format','{{.ID}}'],check=True,capture_output=True,text=True).stdout.splitlines(); assert not cid or cid not in ids
            print('owned browser absent from Docker inventory')
