"""Synthetic direct file/env credential denial for candidate-written train code."""
from dataclasses import replace
from pathlib import Path
import os
import shlex
import subprocess
import sys

import pytest

from lanectl import runner, sandbox


@pytest.mark.parametrize('path', ['/tmp/credential dir', "/tmp/credential'dir", '/tmp/credential\\dir'])
def test_unsupported_credential_paths_fail_closed_before_raw_argv(path, tmp_path):
    sb=sandbox.Sandbox('systemd-run', (), (str(tmp_path),), 60, inaccessible=(path,))
    with pytest.raises(ValueError,match='credential paths'):
        sb.prefix(tmp_path)
    with pytest.raises(ValueError,match='credential paths'):
        sb.wrap_shell('true',tmp_path)


def synthetic_environment(tmp_path):
    home=tmp_path/'operator-home';runtime=tmp_path/'operator-runtime'
    config=tmp_path/'xdg-config';data=tmp_path/'xdg-data';explicit=tmp_path/'loaded-credentials'
    paths=[home/'.config/vuoro/credentials/runner',home/'.config/forgejo/token',
           home/'.local/share/forgejo-cli/keys.json',home/'.ssh/key',home/'.config/sops/age/key',
           config/'vuoro/credentials/runner',config/'forgejo/token',config/'sops/age/key',
           data/'forgejo-cli/keys.json',home/'.local/share/opencode/auth.json',data/'opencode/auth.json',
           home/'.codex/auth.json',home/'.claude/.credentials.json',runtime/'credentials/unit/runner',explicit/'runner']
    for path in paths:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('synthetic-only-not-a-live-secret')
    env=dict(os.environ,HOME=str(home),XDG_CONFIG_HOME=str(config),XDG_DATA_HOME=str(data),
             XDG_RUNTIME_DIR=str(runtime),CREDENTIALS_DIRECTORY=str(explicit),
             FJ_TOKEN='synthetic-forge-token',LANECTL_TEST_API_KEY='synthetic-api-key')
    return env,paths


def command_for_probe(work,paths):
    program=work/'probe.py'
    program.write_text('import os,pathlib,sys\n'+
        'leaks=[]\n'+
        'for name in ("CREDENTIALS_DIRECTORY","FJ_TOKEN","LANECTL_TEST_API_KEY"):\n'+
        '    if name in os.environ: leaks.append("env:"+name)\n'+
        'for path in '+repr([str(p) for p in paths])+':\n'+
        '    try: pathlib.Path(path).read_bytes()\n'+
        '    except (PermissionError,FileNotFoundError): pass\n'+
        '    else: leaks.append("file:"+pathlib.Path(path).name)\n'+
        'pathlib.Path("candidate-output").write_text("writable")\n'+
        'print("BOUNDARY_LEAK:"+",".join(leaks) if leaks else "CREDENTIAL_ISOLATION_OK")\n'+
        'sys.exit(bool(leaks))\n')
    return shlex.join([sys.executable,str(program)])


def test_actual_train_namespace_denies_synthetic_credentials(tmp_path):
    env,paths=synthetic_environment(tmp_path)
    work=tmp_path/'train';work.mkdir()
    cmd=command_for_probe(work,paths)
    git_config=Path(env['HOME'])/'.config/git/config'
    git_config.parent.mkdir(parents=True);git_config.write_text('[core]\n')
    cmd += ' && test -r '+shlex.quote(str(git_config))+' && echo GIT_CONFIG_READABLE'
    sb=sandbox.for_train(readonly=(),writable=(str(work),),timeout_s=60,env=env)
    p=subprocess.run(sb.wrap_shell(cmd,work),shell=True,cwd=work,capture_output=True,text=True)
    assert p.returncode==0,p.stdout+p.stderr
    assert p.stdout.split()==['CREDENTIAL_ISOLATION_OK','GIT_CONFIG_READABLE']
    assert (work/'candidate-output').read_text()=='writable'
    # Same real namespace and clean environment, with only the path guard removed:
    # this must demonstrate direct synthetic-file reads rather than a vacuous check.
    bad=replace(sb,inaccessible=())
    p=subprocess.run(bad.wrap_shell(cmd,work),shell=True,cwd=work,capture_output=True,text=True)
    assert p.returncode==1,p.stdout+p.stderr
    assert 'BOUNDARY_LEAK:file:' in p.stdout


def test_train_setup_and_check_use_isolation_not_worker_none(estate,monkeypatch,tmp_path):
    repo,release,log=estate
    release('train-proof','def test_ok():\n    assert True\n')
    c=runner.admit('implement',log)
    subprocess.run(['git','-C',str(repo),'branch',c.rel.id+'-candidate',c.rel.base_sha],check=True)
    monkeypatch.setattr(runner,'candidates',lambda *a:[{'attempt_id':c.attempt_id,'branch':c.rel.id+'-candidate','title':'proof'}])
    secret=tmp_path/'synthetic-credentials'/'runner';secret.parent.mkdir();secret.write_text('synthetic-only')
    monkeypatch.setenv('CREDENTIALS_DIRECTORY',str(secret.parent))
    monkeypatch.setenv('FJ_TOKEN','synthetic-forge-token')
    probe=f'test -z "${{CREDENTIALS_DIRECTORY+x}}" && test -z "${{FJ_TOKEN+x}}" && ! cat {shlex.quote(str(secret))} >/dev/null 2>&1'
    repos=runner.load_repos();original=repos['target']
    monkeypatch.setattr(runner,'load_repos',lambda:{'target':replace(original,setup_cmd=probe,check_cmd=probe)})
    lane=Path(os.environ['LANECTL_HOME'])/'governance/lanes/implement.toml'
    lane.write_text(lane.read_text().replace('mode = "systemd-run"','mode = "none"'))
    out=runner.build_train(log,'target')
    assert ': PASSED ' in out,out
    train=[e['data'] for e in log.read() if e['type']=='train.built'][-1]
    assert 'PASSED' in runner.recheck_train(log,train['train_id'])


def test_failed_final_setup_cannot_be_hidden_by_green_check(estate,monkeypatch):
    repo,release,log=estate
    release('setup-proof','def test_ok():\n    assert True\n')
    c=runner.admit('implement',log)
    subprocess.run(['git','-C',str(repo),'branch','setup-candidate',c.rel.base_sha],check=True)
    monkeypatch.setattr(runner,'candidates',lambda *a:[{'attempt_id':c.attempt_id,'branch':'setup-candidate','title':'setup'}])
    original=runner.load_repos()['target']
    monkeypatch.setattr(runner,'load_repos',lambda:{'target':replace(original,setup_cmd='exit 71',check_cmd='true')})
    out=runner.build_train(log,'target')
    assert ': FAILED ' in out,out
    assert not [e['data'] for e in log.read() if e['type']=='train.built'][-1]['passed']


def test_historical_land_reconstructs_exact_tip_without_writable_main(estate,monkeypatch,tmp_path):
    from tests.stage8.test_work_sync_extra import _train,_head
    repo,release,log=estate
    release('history-proof','def test_ok():\n    assert True\n')
    base=_head(repo);_train(log,repo,'history-proof',base)
    secret=tmp_path/'loaded-credentials'/'runner';secret.parent.mkdir();secret.write_text('synthetic-only')
    monkeypatch.setenv('CREDENTIALS_DIRECTORY',str(secret.parent))
    probe=f'test -z "${{CREDENTIALS_DIRECTORY+x}}" && ! cat {shlex.quote(str(secret))} >/dev/null 2>&1'
    original=runner.load_repos()['target']
    monkeypatch.setattr(runner,'load_repos',lambda:{'target':replace(original,setup_cmd=probe,check_cmd=probe)})
    real=runner._train_command;locations=[]
    def command(repo,checkout,cmd):
        locations.append(checkout)
        assert runner.git(checkout,'rev-parse','HEAD')==base
        return real(repo,checkout,cmd)
    monkeypatch.setattr(runner,'_train_command',command)
    assert runner.land(log,'tt').startswith('landed')
    assert len(locations)==2 and all(p!=repo and not p.exists() for p in locations)
    assert _head(repo)==base
    assert not (repo/'candidate-output').exists()


def test_historical_checkout_cleanup_survives_check_exception(estate,monkeypatch):
    import pytest
    from tests.stage8.test_work_sync_extra import _train,_head
    repo,release,log=estate
    release('cleanup-proof','def test_ok():\n    assert True\n')
    base=_head(repo);_train(log,repo,'cleanup-proof',base)
    locations=[]
    def explode(repo,checkout,cmd):
        locations.append(checkout)
        raise RuntimeError('synthetic check launcher failure')
    monkeypatch.setattr(runner,'_train_command',explode)
    with pytest.raises(RuntimeError,match='synthetic check launcher'):
        runner.land(log,'tt')
    assert locations and all(not path.exists() for path in locations)
    assert _head(repo)==base
    assert not [e for e in log.read() if e['type']=='item.landed']
    assert not [e['data'] for e in log.read() if e['type']=='train.built'][-1].get('checked_sha')


def test_worker_setup_does_not_inherit_credentials_directory(estate,monkeypatch,tmp_path):
    from lanectl.adapters import AdapterResult
    repo,release,log=estate
    release('worker-env-proof','from calc import sub\n\ndef test_sub():\n    assert sub(5,3)==2\n')
    secret=tmp_path/'loaded-credentials';secret.mkdir()
    secret_file=secret/'runner';secret_file.write_text('synthetic-only')
    monkeypatch.setenv('CREDENTIALS_DIRECTORY',str(secret))
    original=runner.load_repos()['target']
    script=('import os,pathlib\n'
            'readable=True\n'
            f'try: pathlib.Path({str(secret_file)!r}).read_bytes()\n'
            'except (PermissionError,FileNotFoundError): readable=False\n'
            'pathlib.Path("tests/setup-env.txt").write_text(str(("CREDENTIALS_DIRECTORY" in os.environ,readable)))')
    monkeypatch.setattr(runner,'load_repos',lambda:{'target':replace(original,setup_cmd=shlex.join([sys.executable,'-c',script]))})
    observed=[]
    def worker(*,worktree,env,**kwargs):
        worktree=Path(worktree)
        observed.append((worktree/'tests/setup-env.txt').read_text())
        assert 'CREDENTIALS_DIRECTORY' not in env
        (worktree/'src/calc.py').write_text('def add(a,b):\n    return a+b\n\ndef sub(a,b):\n    return a-b\n')
        return AdapterResult('done',0,'ok',None)
    runner.execute(runner.admit('implement',log),log,adapter_fn=worker)
    assert observed==['(False, False)']


def test_worker_namespace_hides_runner_credentials_but_keeps_provider_auth(tmp_path,monkeypatch):
    env,all_paths=synthetic_environment(tmp_path)
    for name in ('HOME','XDG_CONFIG_HOME','XDG_DATA_HOME','CREDENTIALS_DIRECTORY'):
        monkeypatch.setenv(name,env[name])
    runner_paths=[Path(env['HOME'])/'.config/vuoro/credentials/runner',
                  Path(env['XDG_CONFIG_HOME'])/'vuoro/credentials/runner',
                  Path(env['CREDENTIALS_DIRECTORY'])/'runner']
    work=tmp_path/'worker';work.mkdir()
    cmd=command_for_probe(work,runner_paths)
    provider=Path(env['HOME'])/'.codex/auth.json'
    cmd+=' && test -r '+shlex.quote(str(provider))+' && echo PROVIDER_AUTH_READABLE'
    sb=sandbox.from_lane({'mode':'systemd-run'},(str(work),),60)
    # This is also how the specification sandbox replaces other fields.
    sb=replace(sb,readonly=tuple(sb.readonly))
    p=subprocess.run(sb.wrap_shell(cmd,work),shell=True,cwd=work,capture_output=True,text=True)
    assert p.returncode==0,p.stdout+p.stderr
    assert p.stdout.split()==['CREDENTIAL_ISOLATION_OK','PROVIDER_AUTH_READABLE']
    p=subprocess.run(replace(sb,inaccessible=()).wrap_shell(cmd,work),shell=True,cwd=work,capture_output=True,text=True)
    assert p.returncode==1,p.stdout+p.stderr
    assert 'BOUNDARY_LEAK:file:' in p.stdout


def test_coordinated_none_mode_refuses_before_owner_claim(estate,monkeypatch):
    from tests.stage8.test_runner_coordination import configure
    from tests.stage8.test_work_sync_extra import _set_work
    repo,release,log=estate
    release('unsafe-mode-proof','def test_ok():\n    assert True\n')
    _set_work('unsafe-mode-proof','target#12',True)
    owner=configure(monkeypatch)
    lane=Path(os.environ['LANECTL_HOME'])/'governance/lanes/implement.toml'
    lane.write_text(lane.read_text().replace('mode = "systemd-run"','mode = "none"'))
    out=runner.admit('implement',log)
    assert isinstance(out,str) and 'credential-isolating systemd' in out
    assert owner.calls==[]
