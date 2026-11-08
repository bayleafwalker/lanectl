"""Reaper v2: finished-but-undecided attempts get the runner's own decision trail."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lanectl import runner
from lanectl.events import project_items
from lanectl.reap import reap
from tests.seed.test_end_to_end import SUB_TEST, estate, scripted  # estate is a pytest fixture

LATER = datetime.now(timezone.utc) + timedelta(days=1)


def _crash_after(log, keep_type):
    path = Path(log.path)
    lines = path.read_text().splitlines()
    last = max(i for i, line in enumerate(lines) if json.loads(line)["type"] == keep_type)
    path.write_text("\n".join(lines[:last + 1]) + "\n")


def test_recovered_gate_failure_is_rejected_and_consumes_the_attempt(estate):
    repo, release, log = estate
    release("add-sub", SUB_TEST)
    c = runner.admit("implement", log)
    # worker changes nothing: the acceptance test fails, so the gates reject
    runner.execute(c, log, adapter_fn=scripted(lambda wt: None))
    _crash_after(log, "gate.result")

    assert reap(log, now=LATER, older_than_s=60, max_attempts=2) == [c.attempt_id]
    ev = log.read()
    dec = [e["data"] for e in ev if e["type"] == "decision.recorded"]
    assert len(dec) == 1
    assert dec[0]["decision"] == "rejected" and dec[0]["by"] == "gates"
    assert dec[0]["recovered_by"] == "reaper/v2"
    v = project_items(ev)["add-sub"]
    assert v.state == "requeued"
    assert runner.attempts_used(v, 1) == 1       # a gate rejection costs an attempt


def test_recovered_gate_failure_parks_when_attempts_exhausted(estate):
    repo, release, log = estate
    release("add-sub", SUB_TEST)
    c = runner.admit("implement", log)
    runner.execute(c, log, adapter_fn=scripted(lambda wt: None))
    _crash_after(log, "gate.result")

    assert reap(log, now=LATER, older_than_s=60, max_attempts=1) == [c.attempt_id]
    assert project_items(log.read())["add-sub"].state == "parked"
