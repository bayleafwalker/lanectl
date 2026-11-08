"""Acceptance: reap decides finished-but-undecided attempts (planner-owned)."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lanectl import runner
from lanectl.events import project_items
from lanectl.reap import reap
from tests.seed.test_end_to_end import SUB_TEST, estate, scripted  # estate is a pytest fixture

LATER = datetime.now(timezone.utc) + timedelta(days=1)


def good(wt):
    (wt / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
    (wt / "tests" / "test_sub_extra.py").write_text("from calc import sub\n\ndef test_neg():\n    assert sub(1, 2) == -1\n")


def _crash_after(log, keep_type):
    """Simulate a runner death: drop every event after the last `keep_type` event."""
    path = Path(log.path)
    lines = path.read_text().splitlines()
    last = max(i for i, line in enumerate(lines) if json.loads(line)["type"] == keep_type)
    path.write_text("\n".join(lines[:last + 1]) + "\n")


def test_gated_attempt_is_decided(estate):
    repo, release, log = estate
    release("add-sub", SUB_TEST)
    c = runner.admit("implement", log)
    assert "-> candidate" in runner.execute(c, log, adapter_fn=scripted(good))
    _crash_after(log, "gate.result")
    assert project_items(log.read())["add-sub"].state != "candidate"
    assert reap(log, now=LATER, older_than_s=60, max_attempts=2) == [c.attempt_id]
    ev = log.read()
    assert project_items(ev)["add-sub"].state == "candidate"
    decs = [e["data"] for e in ev if e["type"] == "decision.recorded"]
    assert len(decs) == 1 and decs[0]["by"] == "gates" and decs[0]["recovered_by"] == "reaper/v2"
    exp = [e["data"] for e in ev if e["type"] == "experiment.recorded"]
    assert len(exp) == 1 and exp[0]["size"] == "S" and exp[0]["decision"] == "candidate"
    assert reap(log, now=LATER, older_than_s=60, max_attempts=2) == []       # idempotent


def test_attempt_without_gate_results_requeues_as_infra(estate):
    repo, release, log = estate
    release("add-sub", SUB_TEST)
    c = runner.admit("implement", log)
    runner.execute(c, log, adapter_fn=scripted(good))
    _crash_after(log, "attempt.finished")
    assert reap(log, now=LATER, older_than_s=60, max_attempts=2) == [c.attempt_id]
    ev = log.read()
    dec = [e["data"] for e in ev if e["type"] == "decision.recorded"][0]
    assert dec["decision"] == "rejected" and dec["reasons"][0].startswith("infra:")
    v = project_items(ev)["add-sub"]
    assert v.state == "requeued" and runner.attempts_used(v, 1) == 0


def test_recent_finish_is_left_alone(estate):
    repo, release, log = estate
    release("add-sub", SUB_TEST)
    c = runner.admit("implement", log)
    runner.execute(c, log, adapter_fn=scripted(good))
    _crash_after(log, "gate.result")
    assert reap(log, now=datetime.now(timezone.utc), older_than_s=3600, max_attempts=2) == []
