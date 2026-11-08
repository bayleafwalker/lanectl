"""Acceptance: triage emitters (planner-owned)."""

from lanectl.contracts import make_event


def experiment(aid, cls="glue", size="S", model="opencode-go/deepseek-v4.1-flash", decision="candidate"):
    return make_event("experiment.recorded", {"attempt_id": aid, "decision": decision, "elapsed_s": 1.0,
                                              "gates_failed": [], "lane_revision": 2, "model": model,
                                              "rules_revision": "decision-rules/v3", "size": size,
                                              "task_class": cls, "worker": "opencode"},
                      item_id=aid.rsplit("-a", 1)[0])


def gates_candidate(aid):
    return make_event("decision.recorded", {"attempt_id": aid, "by": "gates", "decision": "candidate",
                                            "reasons": [], "rules_revision": "decision-rules/v3"},
                      item_id=aid.rsplit("-a", 1)[0])


def evaluation(aid, verdict):
    return make_event("evaluation.recorded", {"attempt_id": aid, "evaluator": "rules", "verdict": verdict,
                                              "rules_revision": "evaluator/v1", "features": {}, "reasons": []},
                      item_id=aid.rsplit("-a", 1)[0])


def train(tid, attempts, passed=True, excluded=(), check_tail="", ts="2026-11-08T12:00:00Z"):
    e = make_event("train.built", {"attempts": list(attempts), "base_sha": "a" * 40, "check_tail": check_tail,
                                   "excluded": [{"attempt_id": a, "reason": "merge conflict"} for a in excluded],
                                   "passed": passed, "repo": "lanectl", "train_id": tid,
                                   "worktree": f"/w/{tid}"})
    e["ts"] = ts
    return e


def landed(aid, tid, fixes=()):
    return make_event("item.landed", {"attempt_id": aid, "train_id": tid, "fix_commits": list(fixes)},
                      item_id=aid.rsplit("-a", 1)[0])

import hashlib

from lanectl import cli
from lanectl.events import EventLog
from lanectl.triage import failing_tests, from_train, proposals

TAIL = """FAILED tests/stage1/test_x.py::test_a - AssertionError: assert 1 == 2
FAILED tests/stage1/test_x.py::test_b
ERROR tests/stage2/test_y.py - ModuleNotFoundError: No module named 'q'
FAILED tests/stage1/test_x.py::test_a - AssertionError: again
2 failed, 1 error in 0.5s"""


def test_failing_tests_parse():
    assert failing_tests(TAIL) == ["tests/stage1/test_x.py::test_a", "tests/stage1/test_x.py::test_b",
                                   "tests/stage2/test_y.py"]
    assert failing_tests("5 passed") == []


def test_failed_train_proposals():
    ps = from_train(train("train-9", ["aa-a1"], passed=False, check_tail=TAIL))
    assert len(ps) == 3 and all(p["source"] == "train" and p["train_id"] == "train-9" for p in ps)
    fp = hashlib.sha1(b"lanectl:tests/stage1/test_x.py::test_a").hexdigest()
    assert ps[0]["fingerprint"] == fp and "test_a" in ps[0]["summary"]
    assert from_train(train("train-9", ["aa-a1"], passed=True)) == []
    assert len(from_train(train("train-8", ["aa-a1"], passed=False, check_tail="boom"))) == 1


def test_scan_records_once_and_dedupes(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LANECTL_STATE", str(tmp_path))
    log = EventLog()
    for t in (train("train-1", ["aa-a1"], passed=False, check_tail=TAIL, ts="2026-11-08T10:00:00Z"),
              train("train-2", ["bb-a1"], passed=False, check_tail=TAIL, ts="2026-11-08T11:00:00Z")):
        log.append(t["type"], t["data"])
    assert cli.main(["triage", "scan", "--record"]) == 0
    assert cli.main(["triage", "scan", "--record"]) == 0
    assert [e["type"] for e in log.read()].count("triage.proposed") == 6
    open_ = proposals(log.read())
    assert len(open_) == 3 and all(p["count"] == 2 for p in open_)
    assert cli.main(["triage"]) == 0 and "test_b" in capsys.readouterr().out
