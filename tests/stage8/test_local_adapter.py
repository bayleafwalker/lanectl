"""Local inference uses an explicit loopback provider and preserves the sandbox."""
import json
from pathlib import Path

import pytest

from lanectl import adapters_local as local
from lanectl.sandbox import Sandbox


@pytest.mark.parametrize('origin',['https://api.example.com/v1','http://localhost:8020/v1',
    'http://127.0.0.1:8020/v1?fallback=remote','http://user@127.0.0.1:8020/v1',
    'http://127.0.0.1:8020/not-v1'])
def test_unqualified_endpoints_are_refused(origin):
    with pytest.raises(ValueError,match='loopback|origin'):
        local.validate_origin(origin)


def test_profile_cannot_select_another_provider():
    for value in ['opencode-go/flash','local/../cloud','local/model#cloud','local/model/extra']:
        with pytest.raises(ValueError,match='local|profile'):
            local.profile_for(value)
    assert local.profile_for('local/worker-fast')=='worker-fast'


def test_config_has_only_local_provider_and_denies_fallback():
    config=local.provider_config('worker-fast','http://127.0.0.1:8020/v1')
    assert set(config['providers'])=={'lanectl-local'}
    assert config['model']=='lanectl-local/worker-fast'
    assert config['providers']['lanectl-local']['settings']['baseURL']=='http://127.0.0.1:8020/v1'
    rules=config['policies']
    assert {'action':'provider.use','resource':'*','effect':'deny'} in rules
    assert {'action':'provider.use','resource':'lanectl-local','effect':'allow'} in rules
    assert config['mcp']=={'servers':{}}


def test_launch_preserves_named_sandbox_and_readonly_config(tmp_path,monkeypatch):
    monkeypatch.setenv('LANECTL_LOCAL_BASE_URL','http://127.0.0.1:8020/v1')
    monkeypatch.setenv('FJ_TOKEN','should-not-reach-child')
    monkeypatch.setenv('OPENCODE_CONFIG_CONTENT','malicious inherited provider')
    wt=tmp_path/'attempt';wt.mkdir()
    cfg=wt/'runtime/config';cfg.mkdir(parents=True)
    sb=Sandbox('systemd-run',('/projects',),(str(wt),),60,unit='lanectl-test.service')
    cmd,env=local.launch_command(profile='worker-fast',origin='http://127.0.0.1:8020/v1',
        worktree=wt,config_dir=cfg,runtime_dir=cfg.parent,sandbox=sb,
        opencode='/native/opencode',lane_helper=Path('/local/lane.py'),prompt='synthetic',
        timeout_s=60,env={'PATH':'/bin','FJ_TOKEN':'secret'})
    assert '--unit=lanectl-test.service' in cmd
    assert f'-pReadOnlyPaths={cfg}' in cmd
    assert '-i' in cmd and '--standalone' in cmd
    assert any(x==f'OPENCODE_CONFIG_DIR={cfg}' for x in cmd)
    assert 'OPENCODE_DISABLE_PROJECT_CONFIG=1' in cmd
    assert 'OPENCODE_DISABLE_MODELS_FETCH=1' in cmd
    assert not any('FJ_TOKEN' in x or 'malicious' in x for x in cmd)
    assert 'FJ_TOKEN' not in env and 'OPENCODE_CONFIG_CONTENT' not in env
    assert cmd.index('/local/lane.py') < cmd.index('systemd-run') if 'systemd-run' in cmd else True


def test_missing_origin_never_launches_or_falls_back(tmp_path,monkeypatch):
    monkeypatch.delenv('LANECTL_LOCAL_BASE_URL',raising=False)
    result=local.run_local(model='local/worker-fast',worktree=tmp_path,prompt='synthetic',
        status_file=tmp_path/'status.json',timeout_s=20,external=False,sandbox=Sandbox('systemd-run',(),(str(tmp_path),),20))
    assert result.outcome=='failed' and 'BASE_URL' in result.final_tail


def test_external_attestation_is_refused(tmp_path):
    result=local.run_local(model='local/worker-fast',worktree=tmp_path,prompt='synthetic',
        status_file=tmp_path/'status.json',timeout_s=20,external=True,sandbox=Sandbox('systemd-run',(),(str(tmp_path),),20))
    assert result.outcome=='failed' and 'external' in result.final_tail


def test_unknown_native_major_is_refused():
    with pytest.raises(ValueError,match='OpenCode 2'):
        local.validate_version('1.19.0')
    assert local.validate_version('opencode v2.2.5')=='2.2.5'


def test_relay_refuses_redirect_before_sending_prompt_to_other_origin():
    from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
    import threading,urllib.request,urllib.error
    received=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_POST(self):
            received.append(self.path)
            self.send_response(302)
            self.send_header('Location',f'http://127.0.0.1:{self.server.server_port}/leak')
            self.end_headers()
    upstream=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=upstream.serve_forever,daemon=True).start()
    try:
        with local.local_relay(f'http://127.0.0.1:{upstream.server_port}/v1',2) as origin:
            request=urllib.request.Request(origin+'/chat/completions',data=b'{"prompt":"synthetic"}')
            with pytest.raises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(request,timeout=3)
            assert exc.value.code==502
        assert received==['/v1/chat/completions']
    finally:
        upstream.shutdown();upstream.server_close()


def test_model_version_before_policy_fix_is_refused():
    with pytest.raises(ValueError,match='2.2.3'):
        local.validate_version('opencode v2.2.2')


def test_actual_sandbox_makes_provider_configuration_readonly(tmp_path,monkeypatch):
    import os
    wt=tmp_path/'attempt';wt.mkdir()
    bindir=tmp_path/'bin';bindir.mkdir()
    opencode=bindir/'opencode'
    opencode.write_text('''#!/bin/sh
if [ "$1" = --version ]; then echo 'opencode v2.2.5'; exit 0; fi
if touch "$OPENCODE_CONFIG_DIR/tamper" 2>/dev/null; then
 printf '%s\\n' '{"type":"text","part":{"text":"LEAK"}}'
else
 printf '%s\\n' '{"type":"text","part":{"text":"BLOCKED"}}'
fi
''')
    opencode.chmod(0o755)
    helper=tmp_path/'lane.py'
    helper.write_text('import subprocess,sys\nsys.exit(subprocess.call(sys.argv[sys.argv.index("--")+1:]))\n')
    monkeypatch.setenv('PATH',str(bindir)+os.pathsep+os.environ['PATH'])
    monkeypatch.setenv('LANECTL_LOCAL_BASE_URL','http://127.0.0.1:8020/v1')
    monkeypatch.setenv('LANECTL_LOCAL_LANE_HELPER',str(helper))
    sb=Sandbox('systemd-run',(str(tmp_path),),(str(wt),),30,unit='lanectl-local-config-proof.service')
    result=local.run_local(model='local/worker-fast',worktree=wt,prompt='synthetic',
        status_file=tmp_path/'status.json',timeout_s=20,external=False,sandbox=sb)
    assert result.outcome=='done',result.final_tail
    assert result.final_tail=='BLOCKED'
