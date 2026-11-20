"""Native execution must retain owner authority through terminal settlement."""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import os

from lanectl import coordination, integrator, runner, work
from lanectl.adapters import AdapterResult
from lanectl.events import project_items
from tests.stage8.test_work_sync_extra import _set_work

TEST='from calc import sub\n\ndef test_sub():\n    assert sub(5,3)==2\n'


def test_appservice_replacement_binds_original_release_and_owner_item(estate):
    from lanectl.resident_gateway import GO_ROUTE

    _, release, log = estate
    release("replacement", TEST)
    original = runner.admit("implement", log)
    rel = replace(original.rel, work="target#12", work_complete=True)
    lane = replace(original.lane, sandbox={"mode": "appservice"}, routing={GO_ROUTE: 1.0})
    repo = replace(original.repo, train_isolation="appservice")
    binding = runner.delivery_policy.snapshot(lane)
    events = log.read()
    for event in events:
        if event["type"] in ("release.published", "item.claimed"):
            event["data"]["effective_policy"] = binding
        if event["type"] == "item.claimed":
            event["data"]["model"] = GO_ROUTE
    owner = SimpleNamespace(recorded_binding=lambda _: {"item_id": 12})
    predecessor, candidate = runner.appservice_replacement(events, rel, repo, lane, owner)
    assert predecessor == original.attempt_id
    assert candidate.attempt_id == "replacement-a2"
    assert runner.appservice_replacement(events, replace(rel, work="target#13"), repo, lane, owner) is None
    assert runner.appservice_replacement(events, replace(rel, revision=rel.revision + 1),
                                         repo, lane, owner) is None


class Owner:
    def __init__(self):
        self.calls=[];self.active=True
    def start(self,*args,**kwargs):
        self.calls.append(('start',args))
    @contextmanager
    def guard(self,*a,**kw):
        self.cancel=kw.get('on_lost', lambda: None)
        self.assert_active()
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
    assert [c[0] for c in owner.calls] == ['start', 'evidence', 'evidence', 'evidence',
                                          'evidence', 'evidence', 'report']
    evidence = [entry[1] for entry in owner.calls if entry[0] == 'evidence']
    assert [args[1].split(':')[0] for args in evidence] == ['claim', 'gates', 'candidate', 'train', 'landed']
    assert evidence[0][3]['work_id'] == 12
    assert {'gate': 'acceptance', 'passed': True} in evidence[1][3]['checks']
    assert evidence[3][3]['checked_sha'] == evidence[4][3]['landed_sha']
    assert [e['data'] for e in log.read() if e['type']=='work.synced'][-1]['owner_reported']


def test_runner_credential_is_stripped_for_uncoordinated_work(estate,monkeypatch):
    _,release,log=estate
    release('local-proof',TEST)
    configure(monkeypatch)
    path=Path(os.environ['LANECTL_HOME'])/'governance'/'vuoro.toml'
    path.write_text(path.read_text().replace('[repos.target]','[repos.other]'))
    monkeypatch.setattr(coordination,'configured',lambda *a,**k:None)
    observed=[]
    def worker(**kwargs):
        observed.append(kwargs['env'])
        return good(**kwargs)
    runner.execute(runner.admit('implement',log),log,adapter_fn=worker)
    assert observed and observed[0] is not None
    assert 'LANECTL_TEST_TOKEN' not in observed[0]


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

def test_manual_landing_resumes_only_the_admitted_owner_lease(estate, monkeypatch):
    _, release, log = estate
    release('owner-manual', TEST)
    _set_work('owner-manual', 'target#12', True)
    owner = configure(monkeypatch)
    monkeypatch.setattr(owner, 'recorded_binding', lambda attempt: {'item_id': 12}, raising=False)
    monkeypatch.setattr(integrator, '_authority', lambda: {'autonomous_classes': []})
    claim = runner.admit('implement', log)
    assert 'candidate' in runner.execute(claim, log, adapter_fn=good)
    runner.build_train(log, 'target', [claim.attempt_id])
    train = next(e['data']['train_id'] for e in reversed(log.read()) if e['type'] == 'train.built')
    assert 'owner lease required' in runner.land(log, train)
    owner.active = False
    assert 'lease unavailable' in runner.land(log, train, resume_owner=True)
    assert project_items(log.read())['owner-manual'].state == 'in-train'
    owner.active = True
    append = owner.append_evidence

    def refuse_train(*args):
        if args[1].startswith('train:'):
            raise coordination.CoordinationError('train evidence refused')
        append(*args)

    monkeypatch.setattr(owner, 'append_evidence', refuse_train)
    assert 'train evidence refused' in runner.land(log, train, resume_owner=True)
    assert project_items(log.read())['owner-manual'].state == 'in-train'
    monkeypatch.setattr(owner, 'append_evidence', append)
    assert runner.land(log, train, resume_owner=True).startswith('landed')
    assert project_items(log.read())['owner-manual'].state == 'landed'
    assert not any(call[0] == 'report' for call in owner.calls)
