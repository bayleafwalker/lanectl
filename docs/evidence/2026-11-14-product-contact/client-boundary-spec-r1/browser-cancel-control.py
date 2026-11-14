import json, os, signal, subprocess, sys, tempfile, time
from pathlib import Path

root = Path('/tmp/hla-attention-client-boundary-spec')
ledger = root / 'browser-cancel-ledger.json'
ledger.unlink(missing_ok=True)
child = r'''
import json,os,subprocess,sys,time
from pathlib import Path
import tests.test_attention_record_boundary_acceptance as a
original_run=subprocess.run
original_popen=subprocess.Popen
state={}
def popen(args,*pos,**kw):
 p=original_popen(args,*pos,**kw)
 if isinstance(args,list) and 'dev' in args and any(str(x).endswith('/next') for x in args):
  state['next_pid']=p.pid
  state['next_birth']=Path(f'/proc/{p.pid}/stat').read_text().split()[21]
 return p
def run(args,*pos,**kw):
 p=original_run(args,*pos,**kw)
 if isinstance(args,list) and args[:3]==['docker','run','-d'] and p.returncode==0:
  state['cid']=p.stdout.strip(); state['name']=args[args.index('--name')+1]
  state['label']=args[args.index('--label')+1]
  Path(sys.argv[1]).write_text(json.dumps(state))
  while True: time.sleep(1)
 return p
subprocess.Popen=popen
subprocess.run=run
try:
 a.ensure_tools()
 with __import__('tempfile').TemporaryDirectory(prefix='hla-browser-signal-') as d:
  a.browser_codec(Path(d),{}, {})
except KeyboardInterrupt:
 print('received forced cancellation',flush=True)
 raise
'''
env=dict(os.environ,PYTHONPATH=str(root/'base'))
p=subprocess.Popen([sys.executable,'-c',child,str(ledger)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
try:
    birth=Path(f'/proc/{p.pid}/stat').read_text().split()[21]
    for _ in range(180):
        if ledger.exists(): break
        assert p.poll() is None, 'control exited before browser became live'
        time.sleep(.5)
    else: raise RuntimeError('browser launch ledger not produced')
    item=json.loads(ledger.read_text()); item.update(control_pid=p.pid,control_birth=birth,control_pgid=os.getpgid(p.pid))
    label='{{.Id}} {{index .Config.Labels "hla-boundary.owner"}}'
    live=subprocess.run(['docker','inspect','--format',label,item['cid']],capture_output=True,text=True,check=True,timeout=20).stdout.strip()
    assert live==item['cid']+' '+item['label'].split('=',1)[1], (item,live)
    assert Path(f"/proc/{item['next_pid']}/stat").read_text().split()[21]==item['next_birth']
    print(json.dumps(item,sort_keys=True),flush=True)
    os.kill(p.pid,signal.SIGTERM)
    stdout,stderr=p.communicate(timeout=45)
    (root/'browser-cancel-child.log').write_text('stdout:\n'+stdout+'\nstderr:\n'+stderr)
    assert p.returncode != 0, 'interruption falsely succeeded'
    inventory=subprocess.run(['docker','ps','-a','--no-trunc','--format','{{.ID}} {{.Names}}'],capture_output=True,text=True,check=True,timeout=20).stdout
    assert all(item['cid'] not in line and item['name'] not in line for line in inventory.splitlines()), 'owned container remains'
    try: os.killpg(item['next_pid'],0)
    except ProcessLookupError: pass
    else: raise AssertionError('owned Next group remains')
    print('SIGTERM nonzero; exact CID and name absent from Docker inventory; recorded Next group absent',flush=True)
finally:
    if p.poll() is None:
        os.kill(p.pid,signal.SIGTERM)
        try: p.wait(timeout=45)
        except subprocess.TimeoutExpired: print('control failed to exit after signal',file=sys.stderr)
