"""Extra coverage: an approved park is evaluated, and evaluating stays idempotent."""
from pathlib import Path

from lanectl import runner
from lanectl.landing import plan_landing
from tests.seed.test_end_to_end import SUB_TEST, estate, scripted  # estate is a pytest fixture

AUTH = {"revision": 1, "autonomous_classes": [], "fix_budget_lines": 30,
        "allowed_fix_classes": ["spec-gap", "gate-gap"]}


def good(wt):
    (wt / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
    (wt / "tests" / "test_sub_extra.py").write_text("from calc import sub\n\ndef test_neg():\n    assert sub(1, 2) == -1\n")


def _drop(log, etype):
    path = Path(log.path)
    keep = [line for line in path.read_text().splitlines() if f'"type": "{etype}"' not in line]
    path.write_text("\n".join(keep) + "\n")


def _evaluations(log, aid):
    return [e for e in log.read()
            if e["type"] == "evaluation.recorded" and e["data"]["attempt_id"] == aid]


def _parked_without_evaluation(log):
    """Run one attempt that reaches candidate, then park it and drop the evaluation."""
    c = runner.admit("implement", log)
    assert "-> candidate" in runner.execute(c, log, adapter_fn=scripted(good))
    runner.integrator_reject(log, c.attempt_id, "needs review", park=True)
    _drop(log, "evaluation.recorded")
    assert _evaluations(log, c.attempt_id) == []
    return c


def test_approved_park_lands_in_the_shadow_plan(estate):
    repo, release, log = estate
    release("add-sub", SUB_TEST)
    c = _parked_without_evaluation(log)

    assert "approved" in runner.approve(log, c.attempt_id, "reviewed")
    log.append("train.built", {"train_id": "train-1", "repo": "target", "base_sha": "a" * 40,
                               "attempts": [c.attempt_id], "excluded": [], "passed": True})
    assert plan_landing(log.read(), "train-1", AUTH) == [
        {"attempt_id": c.attempt_id, "action": "land"}]


def test_approving_again_keeps_a_single_evaluation(estate):
    repo, release, log = estate
    release("add-sub", SUB_TEST)
    c = _parked_without_evaluation(log)

    runner.approve(log, c.attempt_id, "reviewed")
    assert len(_evaluations(log, c.attempt_id)) == 1
    runner.integrator_reject(log, c.attempt_id, "second look", park=True)
    runner.approve(log, c.attempt_id, "reviewed again")
    assert len(_evaluations(log, c.attempt_id)) == 1
