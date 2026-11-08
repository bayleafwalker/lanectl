"""Triage treats excluded attempts as conflicts, not check failures."""
from __future__ import annotations

import hashlib

from lanectl.contracts import make_event
from lanectl.triage import from_train

PASS_TAIL = ".......                                             [100%]\n172 passed in 21.05s\n"


def train(tid="train-1", *, passed=False, excluded=(), check_tail=PASS_TAIL,
          repo="lanectl", ts="2026-11-08T10:00:00Z"):
    e = make_event("train.built", {"attempts": [], "base_sha": "a" * 40,
                                   "check_tail": check_tail, "excluded": list(excluded),
                                   "passed": passed, "repo": repo, "train_id": tid,
                                   "worktree": f"/w/{tid}"})
    e["ts"] = ts
    return e


def conflict(aid):
    return {"attempt_id": aid, "reason": "merge conflict"}


def test_excluded_attempt_emits_no_check_failure():
    ps = from_train(train(excluded=[conflict("aa-a1")]))
    assert [p["summary"] for p in ps] == ["merge conflict: aa-a1 in train train-1"]
    assert ps[0]["node_id"] == "aa-a1"
    assert ps[0]["source"] == "train" and ps[0]["train_id"] == "train-1"
    assert ps[0]["fingerprint"] == hashlib.sha1(b"lanectl:excluded:aa-a1").hexdigest()


def test_each_exclusion_is_its_own_proposal():
    ps = from_train(train(excluded=[conflict("aa-a1"), conflict("bb-a2")]))
    assert [p["node_id"] for p in ps] == ["aa-a1", "bb-a2"]
    assert len({p["fingerprint"] for p in ps}) == 2


def test_nodes_and_exclusions_are_both_emitted():
    tail = "FAILED tests/test_x.py::test_y - AssertionError\n1 failed, 3 passed\n"
    ps = from_train(train(excluded=[conflict("aa-a1")], check_tail=tail))
    assert sorted(p["node_id"] for p in ps) == ["aa-a1", "tests/test_x.py::test_y"]
    assert not any("check failed" in p["summary"] for p in ps)


def test_whole_train_summary_only_without_nodes_or_exclusions():
    ps = from_train(train(excluded=[], check_tail="ImportError: boom\n"))
    assert len(ps) == 1 and ps[0]["summary"] == "check failed in train train-1"
    # With an exclusion present the whole-train proposal must not appear.
    ps = from_train(train(excluded=[conflict("aa-a1")], check_tail="ImportError: boom\n"))
    assert [p["node_id"] for p in ps] == ["aa-a1"]
