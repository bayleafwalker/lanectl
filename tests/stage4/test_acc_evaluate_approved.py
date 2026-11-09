"""Acceptance: approval records an evaluation (planner-owned)."""
from pathlib import Path

from lanectl import runner
from tests.seed.test_end_to_end import SUB_TEST, estate, scripted  # estate is a pytest fixture


def good(wt):
    (wt / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
    (wt / "tests" / "test_sub_extra.py").write_text("from calc import sub\n\ndef test_neg():\n    assert sub(1, 2) == -1\n")


def _drop(log, etype):
    path = Path(log.path)
    keep = [line for line in path.read_text().splitlines() if f'"type": "{etype}"' not in line]
    path.write_text("\n".join(keep) + "\n")


def _evaluations(log, aid):
    return [e for e in log.read() if e["type"] == "evaluation.recorded" and e["data"]["attempt_id"] == aid]


def test_approve_records_evaluation(estate):
    repo, release, log = estate
    release("add-sub", SUB_TEST)
    c = runner.admit("implement", log)
    assert "-> candidate" in runner.execute(c, log, adapter_fn=scripted(good))
    runner.integrator_reject(log, c.attempt_id, "needs review", park=True)
    _drop(log, "evaluation.recorded")          # as a review-required park leaves it
    assert _evaluations(log, c.attempt_id) == []
    assert "approved" in runner.approve(log, c.attempt_id, "reviewed")
    ev = _evaluations(log, c.attempt_id)
    assert len(ev) == 1 and ev[0]["data"]["verdict"] in ("accept", "reject")


def test_approve_of_unparked_attempt_records_nothing(estate):
    repo, release, log = estate
    release("add-sub", SUB_TEST)
    c = runner.admit("implement", log)
    runner.execute(c, log, adapter_fn=scripted(good))
    _drop(log, "evaluation.recorded")
    assert "not the latest attempt of a parked item" in runner.approve(log, c.attempt_id, "x")
    assert _evaluations(log, c.attempt_id) == []
