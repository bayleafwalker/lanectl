"""Native execution must retain owner authority through terminal settlement."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import os

from lanectl import coordination, integrator, runner, work
from lanectl.adapters import AdapterResult
from lanectl.events import project_items
from tests.stage8.test_work_sync_extra import _set_work

TEST='from calc import sub\n\ndef test_sub():\n    assert sub(5,3)==2\n'


class Owner:
    def __init__(self):
        self.calls=[];self.active=True
    def start(self,*args,**kwargs):
        self.calls.append(('start',args))
    @contextmanager
    def guard(self,*a,**kw):
        self.cancel=kw['on_lost']
        yield self
        self.assert_active()
    def assert_active(self):
        if not self.active:
            self.cancel()
            raise coordination.CoordinationError('lease revoked')
    def append_evidence(self,*a,**kw):
        self.calls.append(('evidence',a))
    def report_outcome(self,*a,**kw):
        self.calls.append(('report',a))
        return {'settled':True,'settlement_effect':'settled'}
    def completion(self,*a):
        return {"closed":True,"status":"done","resolution":"accepted"}


def configure(monkeypatch):
    home=Path(os.environ['LANECTL_HOME'])
    (home/'governance'/'vuoro.toml').write_text('[repos.target]\nendpoint="http://localhost"\nrepo_id="target"\nexpected_environment="test"\ntoken_env="LANECTL_TEST_TOKEN"\n')
    monkeypatch.setenv('LANECTL_TEST_TOKEN','private-test-value')
    owner=Owner()
    monkeypatch.setattr(coordination,'configured',lambda *a,**k:owner)
    monkeypatch.setattr(work,'_call',lambda *a,**k: (_ for _ in ()).throw(AssertionError('coordinated work must not use operator tracker credentials')))
    return owner


def good(*,worktree,env,**kw):
    assert 'LANECTL_TEST_TOKEN' not in env
    wt=Path(worktree)
    (wt/'src'/'calc.py').write_text('def add(a,b):\n    return a+b\n\ndef sub(a,b):\n    return a-b\n')
    (wt/'tests'/'test_extra.py').write_text('from calc import sub\n\ndef test_negative():\n    assert sub(1,2)==-1\n')
    return AdapterResult('done',0,'ok',None)


def test_owner_success_only_after_land_and_no_tracker_double_settlement(estate,monkeypatch):
    _,release,log=estate
    release('owner-proof',TEST);_set_work('owner-proof','target#12',True)
    owner=configure(monkeypatch)
    monkeypatch.setattr(integrator,'_authority',lambda:{'autonomous_classes':['glue'],'fix_budget_lines':30,'allowed_fix_classes':['spec-gap','gate-gap']})
    monkeypatch.setattr(integrator,'_accepted',lambda *a:True)
    runner.execute(runner.admit('implement',log),log,adapter_fn=good)
    assert project_items(log.read())['owner-proof'].state=='landed'
    assert [c[0] for c in owner.calls]==['start','evidence','evidence','report']
    assert [e['data'] for e in log.read() if e['type']=='work.synced'][-1]['owner_reported']


def test_revoked_owner_cannot_accept_candidate(estate,monkeypatch):
    _,release,log=estate
    release('revoked-proof',TEST);_set_work('revoked-proof','target#12',True)
    owner=configure(monkeypatch)
    def revoked(**kwargs):
        res=good(**kwargs)
        owner.active=False
        return res
    out=runner.execute(runner.admit('implement',log),log,adapter_fn=revoked)
    assert 'parked' in out
    assert project_items(log.read())['revoked-proof'].state=='parked'
    assert not any(c[0]=='report' for c in owner.calls)
    assert not [e for e in log.read() if e['type']=='item.landed']


def test_partial_coordinated_release_is_not_claimed(estate,monkeypatch):
    _,release,log=estate
    release('partial-proof',TEST);_set_work('partial-proof','target#12',False)
    owner=configure(monkeypatch)
    out=runner.admit('implement',log)
    assert isinstance(out,str) and 'complete Work outcome' in out
    assert not owner.calls
    assert not [e for e in log.read() if e['type']=='item.claimed']


def test_reference_to_other_repository_never_claims_owner(estate,monkeypatch):
    _,release,log=estate
    release('wrong-work-proof',TEST);_set_work('wrong-work-proof','other#12',True)
    owner=configure(monkeypatch)
    out=runner.admit('implement',log)
    assert isinstance(out,str)
    assert not owner.calls
    assert not [e for e in log.read() if e['type']=='item.claimed']


def test_reported_success_without_owner_acceptance_remains_pending():
    from types import SimpleNamespace
    owner=Owner()
    owner.report_outcome=lambda *a,**kw:{'settled':False,'settlement_effect':'awaiting-verification'}
    owner.completion=lambda *a:{'closed':False,'status':'active','resolution':None}
    assert not work.report_owner_completion(owner,'attempt',SimpleNamespace(id='release'),{'landed_sha':'b'*40,'owner_checks':[{'name':'train','status':'passed'}]})
