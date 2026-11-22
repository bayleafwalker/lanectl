"""Native execution must retain owner authority through terminal settlement."""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import os

import pytest

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


def test_replacement_claim_fences_late_predecessor_projection(estate):
    _, release, log = estate
    release("replacement-projection", TEST)
    original = runner.admit("implement", log)
    claim = next(event["data"] for event in log.read() if event["type"] == "item.claimed")
    successor = "replacement-projection-a2"
    log.append("item.claimed", dict(claim, attempt_id=successor, replaces_attempt_id=original.attempt_id),
               item_id=original.rel.id)
    log.append("gate.result", {"attempt_id": original.attempt_id, "gate": "acceptance",
                               "passed": True, "violations": []}, item_id=original.rel.id)
    for event in ("item.parked", "item.requeued"):
        log.append(event, {"attempt_id": original.attempt_id, "reason": "late decision"},
                   item_id=original.rel.id)
    item = project_items(log.read())[original.rel.id]
    assert item.state == "claimed" and item.open_attempt["attempt_id"] == successor
    assert item.attempts[0]["superseded"] and item.attempts[0]["infra"]
    before = log.read()
    assert "superseded" in runner._coordination_park(original, log, "lease lost")
    assert log.read() == before


def test_tick_recovery_waits_for_owner_before_writing_replacement(estate, monkeypatch):
    from lanectl.resident_gateway import GO_ROUTE

    _, release, log = estate
    release("replace-via-owner", TEST)
    old = runner.admit("implement", log)
    rel = replace(old.rel, work="target#12", work_complete=True)
    lane = replace(old.lane, sandbox={"mode": "appservice"}, routing={GO_ROUTE: 1.0})
    repo = replace(old.repo, train_isolation="appservice")
    fresh = runner.Claim(rel, repo, lane, "replace-via-owner-a2", GO_ROUTE, "opencode")
    seen = []
    held = True

    def acquire(*args, **kwargs):
        seen.append(("start", args[0]))
        if held:
            raise coordination.CoordinationError("lease-held")

    owner = SimpleNamespace(
        start=acquire,
        heartbeat=lambda attempt: seen.append(("heartbeat", attempt)),
        assert_takeover=lambda prior, attempt: seen.append(("verify", prior, attempt)),
    )
    monkeypatch.setattr(runner, "load_lane", lambda _: lane)
    monkeypatch.setattr(runner, "load_releases", lambda: [rel])
    monkeypatch.setattr(runner, "load_repos", lambda: {rel.repo: repo})
    monkeypatch.setattr(runner, "readiness", lambda *args: [])
    monkeypatch.setattr(runner, "appservice_replacement", lambda *args: (old.attempt_id, fresh))
    monkeypatch.setattr(coordination, "configured", lambda _: owner)
    before = log.read()
    with monkeypatch.context() as denial:
        denial.setattr(runner, "_provider_admission", lambda *args: {"decision": "block"})
        assert runner.recover_appservice(lane.lane, log) is None
        assert seen == [] and log.read() == before
    assert runner.recover_appservice(lane.lane, log) is None
    assert log.read() == before
    held = False
    assert runner.recover_appservice(lane.lane, log) == fresh
    assert seen[-2:] == [("heartbeat", fresh.attempt_id), ("verify", old.attempt_id, fresh.attempt_id)]
    assert project_items(log.read())[rel.id].open_attempt["attempt_id"] == fresh.attempt_id


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


def test_publication_wait_rechecks_lease_after_canonical_merge(monkeypatch):
    import pytest

    owner = Owner()
    owner.cancel = lambda: None
    repo, sha = object(), "a" * 40
    observations = []

    def merged(actual_repo, actual_sha, *, timeout_s):
        assert 0 < timeout_s <= 10
        assert actual_repo is repo and actual_sha == sha
        observations.append(actual_sha)
        if len(observations) == 1:
            return False
        owner.active = False
        return True

    waits = []
    cancel = SimpleNamespace(wait=lambda delay: waits.append(delay) or False, is_set=lambda: False)
    monkeypatch.setattr(work, "merged", merged)
    with pytest.raises(coordination.CoordinationError, match="lease revoked"):
        runner._await_canonical_publication(repo, sha, owner, cancel, timeout_s=60)
    assert observations == [sha, sha]
    assert len(waits) == 1


def test_coordinated_publication_waits_inside_original_guard(estate, monkeypatch):
    _, release, log = estate
    release("async-publication", TEST)
    _set_work("async-publication", "target#12", True)
    owner = configure(monkeypatch)
    claim = runner.admit("implement", log)
    repo = replace(claim.repo, landing="pr", publication_cmd="submit checked train")
    claim = replace(claim, repo=repo)
    sha = "a" * 40

    def cycle(log, *, only_attempt):
        assert only_attempt == claim.attempt_id
        log.append("item.landed", {
            "attempt_id": only_attempt, "train_id": "train-async", "landed_sha": sha,
            "fix_commits": [],
        }, item_id=claim.rel.id)

    def await_publication(actual_repo, actual_sha, guard, cancel, *, timeout_s):
        assert actual_repo is repo and actual_sha == sha
        assert guard is owner and not cancel.is_set()
        assert not any(kind == "report" for kind, _ in owner.calls)
        owner.calls.append(("canonical", (actual_sha,)))
        return True

    monkeypatch.setattr(integrator, "cycle", cycle)
    monkeypatch.setattr(runner, "_await_canonical_publication", await_publication, raising=False)
    monkeypatch.setattr(work, "merged", lambda *args: False)
    outcome = runner.execute(claim, log, adapter_fn=good)
    assert [kind for kind, _ in owner.calls][-3:] == ["canonical", "evidence", "report"], outcome


def test_publication_probe_retries_uncertain_read_and_refuses_late_success(monkeypatch):
    owner = Owner()
    now = [0]
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=lambda: now[0]))
    observations = []

    def merged(_repo, _sha, *, timeout_s):
        observations.append(timeout_s)
        if len(observations) == 1:
            raise work._SyncFailed("temporary fetch failure")
        now[0] = 12
        return True

    def wait(delay):
        now[0] += delay

    monkeypatch.setattr(work, "merged", merged)
    cancel = SimpleNamespace(wait=wait, is_set=lambda: False)
    assert not runner._await_canonical_publication(object(), "b" * 40, owner, cancel, timeout_s=12)
    assert observations == [10, 2]


@pytest.mark.parametrize("withdraw", [False, True])
def test_reviewed_train_publishes_only_under_current_matching_lease(estate, monkeypatch, withdraw):
    _, release, log = estate
    release("manual-publish", TEST)
    _set_work("manual-publish", "target#12", True)
    owner = configure(monkeypatch)
    monkeypatch.setattr(owner, "recorded_binding", lambda _: {"item_id": 12}, raising=False)
    monkeypatch.setattr(integrator, "_authority", lambda: {"autonomous_classes": []})
    claim = runner.admit("implement", log)
    assert "candidate" in runner.execute(claim, log, adapter_fn=good)
    assert "PASSED" in runner.build_train(log, "target", [claim.attempt_id])
    train = next(e["data"] for e in reversed(log.read()) if e["type"] == "train.built")
    repo = replace(claim.repo, landing="pr", publication_cmd="submitted through broker")
    monkeypatch.setattr(runner, "load_repos", lambda: {"target": repo})
    monkeypatch.setattr(work, "merged", lambda *args, **kwargs: False)

    submissions = []

    def submit(actual_repo, train_id, sha, *, verify_canonical, submit_timeout_s):
        assert actual_repo == repo and not verify_canonical
        assert 0 < submit_timeout_s <= 40
        assert sha == train["checked_sha"] and train_id == train["train_id"]
        owner.assert_active()
        submissions.append(sha)

    monkeypatch.setattr(integrator, "publish", submit)
    owner.active = False
    assert "lease unavailable" in runner.land(log, train["train_id"], resume_owner=True, publish=True)
    assert not submissions

    owner.active = True
    def unavailable(*args, **kwargs):
        raise RuntimeError("publication endpoint unavailable")

    with monkeypatch.context() as failure:
        failure.setattr(integrator, "publish", unavailable)
        assert "submission pending" in runner.land(log, train["train_id"], resume_owner=True, publish=True)
    assert not [call for call in owner.calls if call[0] == "report"]

    monkeypatch.setattr(runner, "_await_canonical_publication", lambda *args, **kwargs: False)
    assert "publication pending" in runner.land(log, train["train_id"], resume_owner=True, publish=True)
    assert not [call for call in owner.calls if call[0] == "report"]
    if withdraw:
        runner.integrator_reject(log, claim.attempt_id, "Superseded during review", park=True)
        assert "no longer a candidate" in runner.land(
            log, train["train_id"], resume_owner=True, publish=True
        )
        assert submissions == [train["checked_sha"]]
        assert not [call for call in owner.calls if call[0] == "report"]
        return

    def verify(actual_repo, sha, guard, cancel, *, timeout_s):
        assert actual_repo == repo and sha == train["checked_sha"]
        assert guard is owner and not cancel.is_set() and timeout_s > 0
        return True

    monkeypatch.setattr(runner, "_await_canonical_publication", verify)
    result = runner.land(log, train["train_id"], resume_owner=True, publish=True)
    assert result.endswith("; settled"), result
    assert submissions == [train["checked_sha"]] * 2
    assert [call[0] for call in owner.calls][-2:] == ["evidence", "report"]
    assert len([event for event in log.read() if event["type"] == "item.landed"]) == 1
