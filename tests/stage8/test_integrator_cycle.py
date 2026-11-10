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
