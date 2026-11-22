"""Headless integration must remain bounded by explicit class authority."""
from lanectl import integrator, runner

AUTH={'autonomous_classes':['glue'],'fix_budget_lines':30,'allowed_fix_classes':['spec-gap','gate-gap']}


def test_empty_authority_does_nothing(estate, monkeypatch):
    monkeypatch.setattr(integrator,'_authority',lambda:dict(AUTH,autonomous_classes=[]))
    monkeypatch.setattr(runner,'candidates',lambda *a: (_ for _ in ()).throw(AssertionError('inspected candidates')))
    assert integrator.cycle(estate[2]) == []


def test_unapproved_class_never_builds_a_train(estate, monkeypatch):
    repo, release, log=estate
    release('class-proof','def test_ok():\n    assert True\n')
    monkeypatch.setattr(integrator,'_authority',lambda:dict(AUTH,autonomous_classes=['other']))
    monkeypatch.setattr(runner,'candidates',lambda log:[{'item_id':'class-proof','attempt_id':'class-proof-a1'}])
    monkeypatch.setattr(runner,'build_train',lambda *a: (_ for _ in ()).throw(AssertionError('unauthorized train')))
    assert integrator.cycle(log) == []


def test_failed_evaluation_holds_candidate(estate, monkeypatch):
    repo, release, log=estate
    release('eval-proof','def test_ok():\n    assert True\n')
    monkeypatch.setattr(integrator,'_authority',lambda:AUTH)
    monkeypatch.setattr(runner,'candidates',lambda log:[{'item_id':'eval-proof','attempt_id':'eval-proof-a1'}])
    monkeypatch.setattr(integrator.evaluator,'load_rules',lambda: {'revision':1})
    monkeypatch.setattr(integrator.evaluator,'evaluate_attempt',lambda *a: {'verdict':'reject','rules_revision':'evaluator/v1'})
    monkeypatch.setattr(runner,'build_train',lambda *a: (_ for _ in ()).throw(AssertionError('rejected train')))
    assert integrator.cycle(log) == []


def test_closed_unmerged_pr_is_not_reopened(tmp_path, monkeypatch):
    from lanectl.config import RepoSpec
    from types import SimpleNamespace
    import pytest
    repo=RepoSpec(name='r',path=tmp_path,main='main',test_cmd='true',check_cmd='true',worktree_root=tmp_path,landing='pr')
    monkeypatch.setattr(runner,'git',lambda p,*a,**k: 'origin' if a[0]=='config' else 'https://github.com/owner/repo.git')
    calls=[]
    def run(cmd,**kw):
        calls.append(cmd)
        return SimpleNamespace(returncode=0,stdout='[{"number":1,"state":"CLOSED","headRefOid":"'+ 'b'*40 +'"}]',stderr='')
    with pytest.raises(RuntimeError,match='closed without merge'):
        integrator.publish(repo,'tr','b'*40,run=run)
    assert len(calls)==1


def test_candidate_flows_through_train_land_and_replay(estate, monkeypatch):
    from pathlib import Path
    from lanectl.adapters import AdapterResult
    from lanectl.events import project_items
    repo, release, log=estate
    release('full-proof','from calc import sub\n\ndef test_sub():\n    assert sub(5,3)==2\n')
    def worker(*,worktree,**kw):
        wt=Path(worktree)
        (wt/'src'/'calc.py').write_text('def add(a,b):\n    return a+b\n\ndef sub(a,b):\n    return a-b\n')
        (wt/'tests'/'test_extra.py').write_text('from calc import sub\n\ndef test_negative():\n    assert sub(1,2)==-1\n')
        return AdapterResult('done',0,'ok',None)
    assert 'candidate' in runner.execute(runner.admit('implement',log),log,adapter_fn=worker)
    monkeypatch.setattr(integrator,'_authority',lambda:AUTH)
    monkeypatch.setattr(integrator.evaluator,'load_rules',lambda: {'revision':1})
    monkeypatch.setattr(integrator.evaluator,'evaluate_attempt',lambda *a:{'verdict':'accept','rules_revision':'evaluator/v1'})
    lines=integrator.cycle(log)
    assert any(line.startswith('landed') for line in lines), lines
    assert project_items(log.read())['full-proof'].state=='landed'
    assert integrator.cycle(log)==[]
    assert len([e for e in log.read() if e['type']=='item.landed'])==1


def test_many_small_fixes_cannot_exceed_train_budget(tmp_path, monkeypatch):
    from types import SimpleNamespace
    def git(path,*args,**kw):
        if args[0]=='log':
            return 'aaaa fix(attempt-a1): [spec-gap] one\nbbbb fix(attempt-a1): [spec-gap] two'
        return '20\t0\tsrc/f.py'
    monkeypatch.setattr(runner,'git',git)
    assert integrator._fix_warnings(SimpleNamespace(path=tmp_path),{'train_id':'tt','base_sha':'a'*40},[],AUTH)


def test_served_integration_requires_designated_host(monkeypatch):
    from lanectl.remote_events import RemoteEventLog
    log=RemoteEventLog.__new__(RemoteEventLog)
    monkeypatch.setattr(integrator,'_authority',lambda:dict(AUTH,integrator_host='other-host'))
    monkeypatch.setattr(integrator,'_cycle',lambda *a: (_ for _ in ()).throw(AssertionError('effects on wrong host')))
    assert 'designated' in integrator.cycle(log)[0]


def test_served_integration_without_host_is_not_unrestricted(monkeypatch):
    from lanectl.remote_events import RemoteEventLog
    log=RemoteEventLog.__new__(RemoteEventLog)
    monkeypatch.setattr(integrator,'_authority',lambda:AUTH)
    monkeypatch.setattr(integrator,'_cycle',lambda *a: (_ for _ in ()).throw(AssertionError('effects without host pin')))
    assert 'designated' in integrator.cycle(log)[0]


def test_protected_publication_hook_never_substitutes_for_canonical_ancestry(tmp_path, monkeypatch):
    from types import SimpleNamespace

    sha = "a" * 40
    repo = SimpleNamespace(path=tmp_path, name="lanectl", publication_cmd="/protected/submit")
    calls = []
    monkeypatch.setattr(integrator.runner, "git", lambda *args: sha)

    def submit(cmd, cwd, env):
        calls.append((cmd, cwd, env))
        return 0, "publisher accepted request"

    monkeypatch.setattr(integrator.deploy, "_run", submit)
    monkeypatch.setattr(integrator.work, "merged", lambda *args: False)
    assert "awaiting canonical" in integrator.publish(repo, "train-proof", sha)
    assert calls == [("/protected/submit", tmp_path, {
        "LANE_TRAIN_ID": "train-proof", "LANE_CHECKED_SHA": sha, "LANE_REPOSITORY": "lanectl",
    })]
    monkeypatch.setattr(integrator.work, "merged", lambda *args: True)
    assert "merge verified" in integrator.publish(repo, "train-proof", sha)
    import pytest

    with pytest.raises(RuntimeError, match="differs from the checked"):
        integrator.publish(repo, "train-proof", "b" * 40)
    assert len(calls) == 2


def test_scoped_publication_requires_the_exact_workflow_job(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    import pytest

    sha = "b" * 40
    repo = SimpleNamespace(path=tmp_path, main="main")
    monkeypatch.setattr(runner, "git", lambda _, *args, **kwargs:
                        "origin" if args[0] == "config" else "https://github.com/bayleafwalker/lanectl.git")
    monkeypatch.setattr(integrator.work, "merged", lambda *args: True)

    def publish(checks):
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            output = ""
            if command[2] == "list":
                output = json.dumps([{"number": 1, "state": "OPEN", "headRefOid": sha}])
            elif command[-2:] == ["--json", "workflow,name,bucket,state"]:
                output = json.dumps(checks)
            return SimpleNamespace(returncode=0, stdout=output, stderr="")

        result = integrator.publish(repo, "train-proof", sha, run=run, required_check=("ci", "tests"))
        assert calls[-1][-2:] == ["--match-head-commit", sha]
        return result

    passed = {"workflow": "ci", "name": "tests", "bucket": "pass", "state": "SUCCESS"}
    for check in (passed | {"workflow": "other"}, passed | {"state": "SKIPPED"}):
        with pytest.raises(RuntimeError, match="required CI checks"):
            publish([check])
    assert "merge verified" in publish([passed])
