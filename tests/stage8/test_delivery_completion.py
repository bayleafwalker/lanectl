"""Landing must reject unverified trains and defer PR completion."""
from dataclasses import replace
from types import SimpleNamespace
from pathlib import Path
import subprocess

from lanectl import runner, work
from lanectl.contracts import WorkRelease, Acceptance
from lanectl.config import RepoSpec
from tests.stage8.test_work_sync_extra import _train, _head


def test_failed_train_never_lands(estate):
    repo, release, log = estate
    release('failed-proof', 'def test_ok():\n    assert True\n')
    base = _head(repo)
    _train(log, repo, 'failed-proof', base)
    train = [e['data'] for e in log.read() if e['type'] == 'train.built'][-1]
    log.append('train.built', dict(train, passed=False))
    assert 'failed' in runner.land(log, 'tt').lower()
    assert not [e for e in log.read() if e['type'] == 'item.landed']


def test_changed_checked_tip_never_lands(estate):
    repo, release, log = estate
    release('changed-proof', 'def test_ok():\n    assert True\n')
    base = _head(repo)
    _train(log, repo, 'changed-proof', base)
    train = [e['data'] for e in log.read() if e['type'] == 'train.built'][-1]
    log.append('train.built', dict(train, checked_sha='b' * 40))
    assert 'changed' in runner.land(log, 'tt').lower()
    assert not [e for e in log.read() if e['type'] == 'item.landed']


def test_pr_sync_defers_close_until_canonical_merge(tmp_path):
    repo=RepoSpec(name='prrepo', path=tmp_path, main='main', test_cmd='true', check_cmd='true', worktree_root=tmp_path, landing='pr')
    rel=WorkRelease(id='prproof', repo='prrepo', base_sha='a'*40, title='t', outcome='o', task_class='glue', size='S', data_class='public', scope_paths=('src/**',), acceptance=Acceptance(exec=('true',)), work='prrepo#1', work_complete=True)
    calls=[]
    def fake(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0]=='git':
            if 'merge-base' in cmd:
                return SimpleNamespace(returncode=1,stdout='',stderr='not merged')
            if 'ls-remote' in cmd or 'rev-parse' in cmd:
                return SimpleNamespace(returncode=0,stdout='b'*40,stderr='')
            return SimpleNamespace(returncode=0,stdout='',stderr='')
        return SimpleNamespace(returncode=0,stdout='',stderr='')
    result=work.sync(rel,'tr','b'*40,{'prrepo':repo},run=fake)
    assert result['pending_close'] and not result['closed']
    assert not any('status' in cmd for cmd in calls)


def test_empty_canonical_observation_is_not_merge_proof(tmp_path):
    repo=RepoSpec(name='prrepo',path=tmp_path,main='main',test_cmd='true',check_cmd='true',worktree_root=tmp_path,landing='pr')
    import pytest
    with pytest.raises(Exception, match='freshly verified'):
        work.merged(repo, 'b'*40, lambda *a,**k: SimpleNamespace(returncode=0, stdout='', stderr=''))


def test_reconcile_preserves_landing_snapshot_and_skips_confirmed_note(estate, monkeypatch):
    repo, release, log = estate
    release('retry-proof', 'def test_ok():\n    assert True\n')
    rel = WorkRelease(id='retry-proof',repo='target',base_sha='a'*40,title='t',outcome='o',task_class='glue',size='S',data_class='public',scope_paths=('src/**',),acceptance=Acceptance(exec=('true',)),work='target#1',work_complete=True)
    log.append('item.landed', {'attempt_id':'retry-proof-a1','train_id':'tr','fix_commits':[], 'landed_sha':'b'*40,'work_request':{'id':rel.id,'repo':rel.repo,'work':rel.work,'work_complete':True}},item_id=rel.id)
    log.append('work.synced', {'work':rel.work,'train_id':'tr','closed':False,'ok':True,'pending_close':True,'noted':True},item_id=rel.id)
    seen=[]
    def retry(r, train, sha, repos, **kw):
        seen.append((r.work,r.work_complete,sha,kw))
        return {'work':r.work,'train_id':train,'closed':True,'ok':True}
    monkeypatch.setattr(work,'sync',retry)
    changed=replace(rel,work='target#99',work_complete=False)
    assert work.reconcile(log,releases=[changed])[0]['closed']
    assert seen == [('target#1',True,'b'*40,{'skip_note':True})]
    assert work.reconcile(log,releases=[changed]) == []


def test_reconcile_never_guesses_legacy_tip(estate, monkeypatch):
    repo, release, log = estate
    release('old-proof', 'def test_ok():\n    assert True\n')
    rel=WorkRelease(id='old-proof',repo='target',base_sha='a'*40,title='t',outcome='o',task_class='glue',size='S',data_class='public',scope_paths=('src/**',),acceptance=Acceptance(exec=('true',)),work='target#1')
    log.append('item.landed', {'attempt_id':'old-proof-a1','train_id':'tr','fix_commits':[]},item_id=rel.id)
    monkeypatch.setattr(work,'sync',lambda *a,**k: (_ for _ in ()).throw(AssertionError('guessed tip')))
    assert 'no landed_sha' in work.reconcile(log,releases=[rel])[0]['error']


def test_expired_deploy_cannot_authorize_landing(estate, tmp_path):
    from tests.stage8.test_acc_train_deploy import _declare
    repo, release, log=estate
    release('expiry-proof','def test_ok():\n    assert True\n')
    base=_head(repo)
    _train(log,repo,'expiry-proof',base)
    _declare(tmp_path)
    log.append('train.deployed',{'train_id':'tt','repo':'target','namespace':'lane-dev-tt','passed':True,'expires_at':'2000-01-01T00:00:00Z','checked_sha':base})
    assert 'pass its health check' in runner.land(log,'tt')
    assert not [e for e in log.read() if e['type']=='item.landed']


def test_landing_replay_does_not_duplicate_receipts(estate):
    repo, release, log=estate
    release('replay-proof','def test_ok():\n    assert True\n')
    _train(log,repo,'replay-proof',_head(repo))
    assert runner.land(log,'tt').startswith('landed')
    assert runner.land(log,'tt').startswith('landed')
    assert len([e for e in log.read() if e['type']=='item.landed']) == 1


def test_land_does_not_reread_checked_branch_tip(estate, monkeypatch):
    repo, release, log=estate
    release('race-proof','def test_ok():\n    assert True\n')
    base=_head(repo)
    _train(log,repo,'race-proof',base)
    train=[e['data'] for e in log.read() if e['type']=='train.built'][-1]
    log.append('train.built',dict(train,checked_sha=base))
    real=runner.git; reads=[]
    def git(path,*args,**kwargs):
        if args==('rev-parse','train/tt'):
            reads.append(True)
            if len(reads)>1:
                return 'f'*40
        return real(path,*args,**kwargs)
    monkeypatch.setattr(runner,'git',git)
    assert runner.land(log,'tt').startswith('landed')
    assert len(reads)==1
    assert [e['data']['landed_sha'] for e in log.read() if e['type']=='item.landed']==[base]


def test_completed_deploy_landing_replays_after_teardown(estate,tmp_path):
    from tests.stage8.test_acc_train_deploy import _declare
    repo,release,log=estate
    release('done-proof','def test_ok():\n    assert True\n')
    base=_head(repo);_train(log,repo,'done-proof',base);_declare(tmp_path)
    log.append('train.deployed',{'train_id':'tt','repo':'target','namespace':'lane-dev-tt','passed':True,'expires_at':'2099-01-01T00:00:00Z','checked_sha':base})
    assert runner.land(log,'tt').startswith('landed')
    assert runner.land(log,'tt').startswith('landed')
    assert len([e for e in log.read() if e['type']=='item.landed'])==1


def test_fixed_train_needs_fresh_recheck(estate):
    repo,release,log=estate
    release('fix-proof','def test_ok():\n    assert True\n')
    base=_head(repo);_train(log,repo,'fix-proof',base)
    train=[e['data'] for e in log.read() if e['type']=='train.built'][-1]
    log.append('train.built',dict(train,checked_sha=base))
    checkout=Path(train['worktree'])
    subprocess.run(['git','-C',str(repo),'worktree','add',str(checkout),'train/tt'],check=True,capture_output=True)
    (checkout/'notes.md').write_text('bounded fix\n')
    subprocess.run(['git','-C',str(checkout),'add','notes.md'],check=True)
    subprocess.run(['git','-C',str(checkout),'-c','user.name=test','-c','user.email=test@example.invalid','commit','-m','fix(fix-proof-a1): [spec-gap] note'],check=True,capture_output=True)
    assert 'changed' in runner.land(log,'tt')
    assert 'PASSED' in runner.recheck_train(log,'tt')
    assert runner.land(log,'tt').startswith('landed')


def test_recheck_invalidates_a_tip_changed_during_check(estate,monkeypatch):
    repo,release,log=estate
    release('moving-proof','def test_ok():\n    assert True\n')
    base=_head(repo);_train(log,repo,'moving-proof',base)
    train=[e['data'] for e in log.read() if e['type']=='train.built'][-1]
    checkout=Path(train['worktree'])
    subprocess.run(['git','-C',str(repo),'worktree','add',str(checkout),'train/tt'],check=True,capture_output=True)
    real=runner.git;reads=[]
    def git(path,*args,**kwargs):
        if Path(path)==checkout and args==('rev-parse','HEAD'):
            reads.append(True)
            if len(reads)>1:
                return 'f'*40
        return real(path,*args,**kwargs)
    monkeypatch.setattr(runner,'git',git)
    assert 'FAILED' in runner.recheck_train(log,'tt')
    assert not [e['data'] for e in log.read() if e['type']=='train.built'][-1]['passed']
    assert not [e for e in log.read() if e['type']=='item.landed']
