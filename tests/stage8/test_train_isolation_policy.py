"""Weaker train isolation is explicit and never eligible for coordination."""
from dataclasses import replace
import json
import os
from pathlib import Path
import shlex
import sys

import pytest

from lanectl import doctor, runner
from lanectl.config import load_repos
from lanectl.contracts import ContractError


def repo_policy(value):
    path=Path(os.environ['LANECTL_HOME'])/'governance/repos.toml'
    path.write_text(path.read_text()+f'\ntrain_isolation = {json.dumps(value)}\n')


@pytest.mark.parametrize('value',['none','invalid',False])
def test_invalid_isolation_never_silently_falls_back(estate,value):
    repo_policy(value)
    with pytest.raises(ContractError):
        load_repos()


def test_default_namespace_and_explicit_environment_preserve_host_ownership(estate,monkeypatch,tmp_path):
    repo,_,_=estate
    assert load_repos()['target'].train_isolation=='namespace'
    repo_policy('environment')
    policy=load_repos()['target']
    secret=tmp_path/'synthetic-credential';secret.write_text('synthetic-only')
    monkeypatch.setenv('CREDENTIALS_DIRECTORY',str(tmp_path))
    monkeypatch.setenv('FJ_TOKEN','synthetic-token')
    code=('import os,pathlib;'
          'assert "CREDENTIALS_DIRECTORY" not in os.environ;'
          'assert "FJ_TOKEN" not in os.environ;'
          f'assert pathlib.Path({str(secret)!r}).read_text()=="synthetic-only";'
          'print(os.stat("/").st_uid)')
    p=runner._train_command(policy,repo,shlex.join([sys.executable,'-c',code]))
    assert p.returncode==0,p.stdout+p.stderr
    assert p.stdout.strip()==str(os.stat('/').st_uid)


def test_coordinated_environment_mode_refuses_admission(estate,monkeypatch):
    from tests.stage8.test_runner_coordination import configure
    from tests.stage8.test_work_sync_extra import _set_work
    _,release,log=estate
    release('unfenced-proof','def test_ok():\n    assert True\n')
    _set_work('unfenced-proof','target#12',True)
    owner=configure(monkeypatch)
    repo_policy('environment')
    result=runner.admit('implement',log)
    assert isinstance(result,str) and 'namespace train isolation' in result
    assert owner.calls==[]
    assert not [e for e in log.read() if e['type']=='item.claimed']


def test_environment_mode_cannot_reach_owner_or_execute_after_policy_change(estate,monkeypatch,tmp_path):
    from tests.stage8.test_runner_coordination import configure
    from tests.stage8.test_work_sync_extra import _set_work
    repo,release,log=estate
    release('changed-isolation','def test_ok():\n    assert True\n')
    _set_work('changed-isolation','target#12',True)
    claim=runner.admit('implement',log)
    owner=configure(monkeypatch)
    claim=replace(claim,repo=replace(claim.repo,train_isolation='environment'))
    assert 'parked' in runner.execute(claim,log)
    assert owner.calls==[]
    sentinel=tmp_path/'must-not-run'
    p=runner._train_command(claim.repo,repo,'touch '+shlex.quote(str(sentinel)))
    assert p.returncode!=0 and 'namespace train isolation' in p.stderr
    assert not sentinel.exists()


def test_doctor_names_environment_only_repos_and_errors_on_coordinated_ones(estate):
    root=Path(os.environ['LANECTL_HOME'])
    repo_policy('environment')
    repos=load_repos()
    assert doctor.check_train_isolation(root,repos)==[]
    cfg=root/'governance/vuoro.toml'
    cfg.write_text('[repos.other]\ncredential_name="runner"\n')
    findings=doctor.check_train_isolation(root,repos)
    assert len(findings)==1 and findings[0].level==doctor.WARN
    assert 'target' in findings[0].detail and 'same-user credential files' in findings[0].detail
    cfg.write_text('[repos.target]\ncredential_name="runner"\n')
    findings=doctor.check_train_isolation(root,repos)
    assert any(f.level==doctor.ERROR and 'target' in f.detail for f in findings)
