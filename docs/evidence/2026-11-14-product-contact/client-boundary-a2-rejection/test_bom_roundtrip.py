"""Independent whole-ID BOM checks using the frozen real-browser fixture."""
import importlib.util, json, os, subprocess
from pathlib import Path
import pytest

REPO = Path(os.environ['HLA_BOM_CHECKOUT']).resolve()
FROZEN = REPO / 'tests/test_attention_record_boundary_acceptance.py'
assert __import__('hashlib').sha256(FROZEN.read_bytes()).hexdigest() == 'c57154ceb6f60f1a01898ace9fa1ab9bfd9e222a6c06498648f6a0bdf09ea038'
spec = importlib.util.spec_from_file_location('frozen_boundary', FROZEN)
f = importlib.util.module_from_spec(spec); spec.loader.exec_module(f)
VALUES = ['\ufeffa', '\ufeff']
INPUTS = {'values': VALUES, 'invalid': [], 'kinds': []}
EXPECTED = {'encoded': [f.key(v) for v in VALUES], 'decoded': VALUES, 'invalid': [], 'kinds': []}

@pytest.fixture(scope='module', autouse=True)
def tools():
    f.ensure_tools()
    yield
    if f.DEPS_TMP: f.DEPS_TMP.cleanup()

def test_node_roundtrip(tmp_path):
    src=tmp_path/'src'; src.mkdir(); (src/'node_modules').symlink_to(f.PINNED_MODULES, target_is_directory=True)
    import shutil
    shutil.copy2(f.WEB/'lib/attention-key.ts',src/'attention-key.ts')
    env=dict(os.environ,PATH=f.NODE+':'+os.environ.get('PATH',''))
    r=subprocess.run([str(f.PINNED_MODULES/'.bin/tsc'),str(src/'attention-key.ts'),'--target','ES2022','--module','commonjs','--moduleResolution','node','--lib','ES2022,DOM','--types','node','--skipLibCheck','--outDir',str(tmp_path/'out')],cwd=src,env=env,capture_output=True,text=True)
    assert r.returncode==0,r.stdout+r.stderr
    js='const m=require(process.argv[1]); const v=JSON.parse(process.argv[2]); console.log(JSON.stringify({encoded:v.map(x=>m.encodeAttentionKey(x)),decoded:v.map(x=>m.decodeAttentionKey(m.encodeAttentionKey(x)))}))'
    r=subprocess.run(['node','-e',js,str(tmp_path/'out/attention-key.js'),json.dumps(VALUES)],env=env,capture_output=True,text=True)
    assert r.returncode==0,r.stderr
    actual=json.loads(r.stdout);print('actual Node',json.dumps(actual,ensure_ascii=True),flush=True)
    assert actual=={k:EXPECTED[k] for k in ('encoded','decoded')}

def test_browser_roundtrip(tmp_path, monkeypatch):
    original = subprocess.run
    def capture(*args, **kwargs):
        result = original(*args, **kwargs)
        command = args[0]
        if isinstance(command, list) and len(command)>1 and str(command[1]).endswith('browser.cjs'):
            print('actual browser', result.stdout.strip(), flush=True)
        return result
    monkeypatch.setattr(f.subprocess, 'run', capture)
    f.browser_codec(tmp_path, INPUTS, EXPECTED)
