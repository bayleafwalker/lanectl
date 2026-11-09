"""Acceptance: decision-record gaps closed (planner-owned)."""
from datetime import datetime, timedelta, timezone

from lanectl import report, runner
from lanectl.contracts import make_event
from lanectl.coverage import coverage
from lanectl.reap import reap
from tests.seed.test_end_to_end import SUB_TEST, scripted  # estate comes from tests/stage7/conftest.py

LATER = datetime.now(timezone.utc) + timedelta(days=1)


def good(wt):
    (wt / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
    (wt / "tests" / "test_sub_extra.py").write_text("from calc import sub\n\ndef test_neg():\n    assert sub(1, 2) == -1\n")


def _dec(log, **m):
    return [e["data"] for e in log.read() if e["type"] == "lane.decision"
            and all(e["data"].get(k) == v for k, v in m.items())]


def test_coverage_starts_at_first_record():
    old = make_event("item.claimed", {"attempt_id": "aa-a1", "lane": "implement", "model": "m", "worker": "w"},
                     item_id="aa", ts="2026-11-01T00:00:00Z")
    first = make_event("lane.decision", {"decision_id": "dec-1", "kind": "dispatch", "phase": "applied",
                       "chosen": "m", "mechanism": "weighted-hash/v1", "policy_revision": "r",
                       "subject": {"item_id": "bb", "attempt_id": "bb-a1"}}, item_id="bb", ts="2026-11-09T00:00:00Z")
    new = make_event("item.claimed", {"attempt_id": "bb-a1", "lane": "implement", "model": "m", "worker": "w"},
                     item_id="bb", ts="2026-11-09T00:00:01Z")
    c = coverage([old, first, new])
    assert c.get("_since") == "2026-11-09T00:00:00Z" and c["dispatch"] == {"expected": 1, "recorded": 1, "coverage": 1.0}
    assert "_since" in coverage([old]) and coverage([old])["_since"] is None
    assert "decision_coverage (since 2026-11-09T00:00:00Z):" in report.format_report(report.build_report([old, first, new]))


def test_evaluation_and_approval_record_acceptance(estate):
    repo, release, log = estate
    release("add-sub", SUB_TEST)
    c = runner.admit("implement", log)
    assert "-> candidate" in runner.execute(c, log, adapter_fn=scripted(good))
    prop = _dec(log, kind="acceptance", phase="proposed")
    assert len(prop) == 1 and prop[0]["subject"]["attempt_id"] == c.attempt_id
    assert prop[0]["mechanism"] == "evaluator-rules" and prop[0]["chosen"] in ("accept", "reject")
    runner.integrator_reject(log, c.attempt_id, "needs a look", park=True)
    esc = _dec(log, kind="escalation", mechanism="integrator")
    assert len(esc) == 1 and esc[0]["chosen"] == "park" and esc[0]["subject"]["attempt_id"] == c.attempt_id
    runner.approve(log, c.attempt_id, "ok")
    appl = _dec(log, kind="acceptance", phase="applied")
    assert len(appl) == 1 and appl[0]["chosen"] == "candidate" and appl[0]["proposal_id"] == prop[0]["decision_id"]


def test_integrator_requeue_records_rerun(estate):
    repo, release, log = estate
    release("add-sub", SUB_TEST)
    c = runner.admit("implement", log)
    runner.execute(c, log, adapter_fn=scripted(good))
    runner.integrator_reject(log, c.attempt_id, "wrong approach")
    r = _dec(log, kind="rerun", mechanism="integrator")
    assert len(r) == 1 and r[0]["chosen"] == "requeue" and r[0]["reasons"] == ["wrong approach"]


def test_reaper_records_rerun(estate):
    repo, release, log = estate
    release("add-sub", SUB_TEST)
    c = runner.admit("implement", log)
    assert reap(log, now=LATER, older_than_s=60, max_attempts=2) == [c.attempt_id]
    r = _dec(log, kind="rerun", mechanism="reaper/v2")
    assert len(r) == 1 and r[0]["subject"]["attempt_id"] == c.attempt_id
