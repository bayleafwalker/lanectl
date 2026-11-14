import json,os,signal,subprocess,sys,tempfile,time
from pathlib import Path
with tempfile.TemporaryDirectory(prefix='hla-boundary-cancel-') as d:
    ledger=Path(d)/'ledger.json'
    child='''import json,time,sys
from pathlib import Path
from tests.test_attention_record_boundary_acceptance import Lab
with Lab(Path(sys.argv[1])/'lab') as lab:
 Path(sys.argv[1],'ledger.json').write_text(json.dumps({'next_pid':lab.proc.pid}))
 while True: time.sleep(1)
'''
    env=dict(os.environ,PYTHONPATH='/tmp/hla-attention-client-boundary-spec/base')
    p=subprocess.Popen([sys.executable,'-c',child,d],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        for _ in range(120):
            if ledger.exists(): break
            assert p.poll() is None,'fixture exited before readiness'
            time.sleep(.5)
        else: raise RuntimeError('no fixture ledger')
        pid=json.loads(ledger.read_text())['next_pid']; os.kill(p.pid,signal.SIGTERM); stdout,stderr=p.communicate(timeout=30)
        assert p.returncode!=0,'interrupt unexpectedly succeeded'
        try: os.killpg(pid,0)
        except ProcessLookupError: print('SIGTERM interrupted fixture; owned Next group absent')
        else: raise AssertionError('Next group survived cancellation')
        print('exit',p.returncode)
    finally:
        if p.poll() is None: p.kill();p.wait()
