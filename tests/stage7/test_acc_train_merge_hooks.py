"""Acceptance: train merges respect commit hooks and name real failures (planner-owned)."""
import stat

from lanectl import runner
from tests.seed.test_end_to_end import SUB_TEST, estate, scripted  # estate is a pytest fixture


def good(wt):
    (wt / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
    (wt / "tests" / "test_sub_extra.py").write_text("from calc import sub\n\ndef test_neg():\n    assert sub(1, 2) == -1\n")


def _hook(repo, body):
    h = repo / ".git" / "hooks" / "commit-msg"
    h.write_text("#!/bin/sh\n" + body)
    h.chmod(h.stat().st_mode | stat.S_IXUSR)


def _train(log):
    return [e["data"] for e in log.read() if e["type"] == "train.built"][-1]


def test_merge_subject_passes_a_merge_only_hook(estate):
    repo, release, log = estate
    release("add-sub", SUB_TEST)
    c = runner.admit("implement", log)
    assert "-> candidate" in runner.execute(c, log, adapter_fn=scripted(good))
    _hook(repo, 'head -1 "$1" | grep -q "^Merge " || { echo "subject must start with Merge" >&2; exit 1; }\n')
    runner.build_train(log, "target")
    t = _train(log)
    assert t["attempts"] == [c.attempt_id] and t["excluded"] == [] and t["passed"] is True


def test_hook_rejection_is_not_called_a_conflict(estate):
    repo, release, log = estate
    release("add-sub", SUB_TEST)
    c = runner.admit("implement", log)
    runner.execute(c, log, adapter_fn=scripted(good))
    _hook(repo, 'echo "policy says no" >&2; exit 1\n')
    runner.build_train(log, "target")
    ex = _train(log)["excluded"]
    assert len(ex) == 1 and ex[0]["reason"].startswith("merge failed:") and "policy says no" in ex[0]["reason"]
