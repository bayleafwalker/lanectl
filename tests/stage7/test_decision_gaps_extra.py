"""Extra coverage for the remaining decision-record gaps (not planner acceptance)."""
import json
import os
import textwrap
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lanectl import decisions, report, runner
from lanectl.contracts import make_event
from lanectl.coverage import coverage
from lanectl.events import EventLog
from lanectl.reap import reap
from tests.seed.test_end_to_end import SUB_TEST, scripted  # estate comes from tests/stage7/conftest.py

LATER = datetime.now(timezone.utc) + timedelta(days=1)


def good(wt):
    (wt / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
    (wt / "tests" / "test_sub_extra.py").write_text("from calc import sub\n\ndef test_neg():\n    assert sub(1, 2) == -1\n")


def wrong(wt):
    (wt / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return b - a\n")
    (wt / "tests" / "test_sub_extra.py").write_text("from calc import sub\n\ndef test_neg():\n    assert sub(2, 1) == -1\n")


def _dec(log, **match):
    return [e["data"] for e in log.read() if e["type"] == "lane.decision"
            and all(e["data"].get(k) == v for k, v in match.items())]


def _of(log, etype):
    return [e["data"] for e in log.read() if e["type"] == etype]


def _crash_after(log, keep_type):
    """Simulate a runner death: drop every event after the last `keep_type` event."""
    path = Path(log.path)
    lines = path.read_text().splitlines()
    last = max(i for i, line in enumerate(lines) if json.loads(line)["type"] == keep_type)
    path.write_text("\n".join(lines[:last + 1]) + "\n")


def _policy_home():
    gov = Path(os.environ["LANECTL_HOME"]) / "governance"
    (gov / "allocation.toml").write_text(textwrap.dedent("""
        revision = 9
        [providers.scripted]
        unit = "output_tokens"
        expiring = true
        pool = "scripted:test"
        [[providers.scripted.windows]]
        name = "5h"
        length_s = 18000
        budget = 1000000
        [providers.scripted.estimates]
        S = 15000
        """))


def test_coverage_ignores_history_before_the_first_decision():
    old = make_event("item.parked", {"reason": "old"}, item_id="aa", ts="2026-11-01T00:00:00Z")
    first = make_event("lane.decision", {"decision_id": "dec-1", "kind": "dispatch",
                       "phase": "applied", "chosen": "m", "mechanism": "weighted-hash/v1",
                       "policy_revision": "r", "subject": {"item_id": "bb", "attempt_id": "bb-a1"}},
                       item_id="bb", ts="2026-11-09T00:00:00Z")
    new_claim = make_event("item.claimed", {"attempt_id": "bb-a1", "lane": "implement",
                           "model": "m", "worker": "w"},
                           item_id="bb", ts="2026-11-09T00:00:01Z")
    new = make_event("evaluation.recorded", {"attempt_id": "bb-a1", "evaluator": "e",
                     "verdict": "accept", "rules_revision": "r"},
                     item_id="bb", ts="2026-11-09T00:00:02Z")

    c = coverage([old, first, new_claim, new])
    assert c["_since"] == "2026-11-09T00:00:00Z"
    assert c["dispatch"] == {"expected": 1, "recorded": 1, "coverage": 1.0}
    assert c["acceptance"] == {"expected": 1, "recorded": 0, "coverage": 0.0}
    assert c["escalation"] == {"expected": 0, "recorded": 0, "coverage": None}

    empty = coverage([old])
    assert empty["_since"] is None and empty["escalation"]["expected"] == 1
    assert "decision_coverage (since -):" in report.format_report(report.build_report([old]))


def test_evaluator_proposal_carries_the_evaluation_revision(estate):
    repo, release, log = estate
    home = Path(os.environ["LANECTL_HOME"])
    (home / "governance" / "evaluator.toml").write_text('revision = 3\ndefault = "accept"\n')
    release("add-sub", SUB_TEST)
    c = runner.admit("implement", log)

    runner.execute(c, log, adapter_fn=scripted(good))

    ev = _of(log, "evaluation.recorded")
    prop = _dec(log, kind="acceptance", phase="proposed")
    assert len(ev) == 1 and len(prop) == 1
    assert prop[0]["chosen"] == ev[0]["verdict"] == "accept"
    assert prop[0]["policy_revision"] == ev[0]["rules_revision"] == "evaluator/v3"
    assert prop[0]["mechanism"] == "evaluator-rules"
    assert prop[0]["subject"] == {"item_id": "add-sub", "attempt_id": c.attempt_id}


def test_applied_acceptance_without_a_proposal_omits_the_field(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    did = decisions.acceptance_applied(log, item_id="it", attempt_id="it-a1")
    data = log.read()[0]["data"]
    assert data["decision_id"] == did and "proposal_id" not in data
    assert data["chosen"] == "candidate" and data["mechanism"] == "integrator"


def test_reaped_undecided_attempt_records_a_reaper_rerun(estate):
    repo, release, log = estate
    release("add-sub", SUB_TEST)
    c = runner.admit("implement", log)
    runner.execute(c, log, adapter_fn=scripted(wrong))
    _crash_after(log, "attempt.finished")

    assert reap(log, now=LATER, older_than_s=60, max_attempts=2) == [c.attempt_id]
    rerun = _dec(log, kind="rerun", mechanism="reaper/v2")
    assert len(rerun) == 1
    assert rerun[0]["chosen"] == "requeue"
    assert rerun[0]["subject"] == {"item_id": "add-sub", "attempt_id": c.attempt_id}
    assert rerun[0]["reasons"] == ["infra: runner died before gates"]


def test_execute_holds_the_log_lock_while_reconciling_capacity(estate, monkeypatch):
    repo, release, log = estate
    _policy_home()
    release("add-sub", SUB_TEST)
    c = runner.admit("implement", log)

    depth = {"n": 0}
    real_locked, real_append = log.locked, log.append

    @contextmanager
    def locked():
        depth["n"] += 1
        try:
            with real_locked():
                yield log
        finally:
            depth["n"] -= 1

    def append(etype, data, *, item_id=None):
        if etype == "capacity.reconciled":
            assert depth["n"] > 0, "reconciliation must hold the log lock"
        return real_append(etype, data, item_id=item_id)

    monkeypatch.setattr(log, "locked", locked)
    monkeypatch.setattr(log, "append", append)
    runner.execute(c, log, adapter_fn=scripted(good))

    rec = _of(log, "capacity.reconciled")
    assert rec == [{"reservation_id": f"res-{c.attempt_id}", "actual": None,
                    "outcome": "completed"}]
