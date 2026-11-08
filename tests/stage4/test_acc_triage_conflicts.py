"""Acceptance: triage names merge-conflict exclusions (planner-owned)."""
from lanectl.triage import from_train

TAIL_OK = ".......                                             [100%]\n172 passed in 21.05s\n"


def _train(excluded, tail=TAIL_OK, attempts=()):
    return {"type": "train.built", "data": {
        "train_id": "train-1", "repo": "lanectl", "passed": False, "attempts": list(attempts),
        "excluded": excluded, "check_tail": tail}}


def test_conflict_exclusions_are_proposed_per_attempt():
    ev = _train([{"attempt_id": "aa-a1", "reason": "merge conflict"},
                 {"attempt_id": "bb-a2", "reason": "merge conflict"}])
    out = from_train(ev)
    assert [p["summary"] for p in out] == ["merge conflict: aa-a1 in train train-1",
                                           "merge conflict: bb-a2 in train train-1"]
    assert [p["node_id"] for p in out] == ["aa-a1", "bb-a2"]
    assert not any("check failed" in p["summary"] for p in out)
    assert from_train(_train([{"attempt_id": "aa-a1", "reason": "merge conflict"}]))[0]["fingerprint"] == out[0]["fingerprint"]


def test_failing_tests_and_exclusions_both_reported():
    tail = "FAILED tests/test_x.py::test_y - AssertionError\n1 failed, 3 passed\n"
    out = from_train(_train([{"attempt_id": "aa-a1", "reason": "merge conflict"}], tail=tail))
    assert sorted(p["node_id"] for p in out) == ["aa-a1", "tests/test_x.py::test_y"]


def test_whole_train_only_without_nodes_or_exclusions():
    out = from_train(_train([], tail="ImportError: boom\n"))
    assert len(out) == 1 and out[0]["summary"] == "check failed in train train-1"
