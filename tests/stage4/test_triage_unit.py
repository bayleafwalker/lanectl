"""Unit coverage for the triage emitters and the scan/list commands."""
from __future__ import annotations

import hashlib

import pytest

from lanectl import cli
from lanectl.contracts import make_event
from lanectl.events import EventLog
from lanectl.triage import failing_tests, from_train, proposals, scan, unscanned

TAIL = """FAILED tests/a.py::test_one - AssertionError: bad
FAILED tests/a.py::test_one - AssertionError: again
ERROR tests/b.py - ImportError: nope
3 failed, 1 error in 0.1s"""


def train(tid, *, passed=False, check_tail="", ts="2026-11-08T10:00:00Z"):
    e = make_event("train.built", {"attempts": ["aa-a1"], "base_sha": "a" * 40,
                                   "check_tail": check_tail, "excluded": [],
                                   "passed": passed, "repo": "lanectl", "train_id": tid,
                                   "worktree": f"/w/{tid}"})
    e["ts"] = ts
    return e


def test_failing_tests_dedupes_and_ignores_success():
    assert failing_tests(TAIL) == ["tests/a.py::test_one", "tests/b.py"]
    assert failing_tests("5 passed in 0.2s") == []


def test_whole_train_fallback_fingerprint():
    ps = from_train(train("train-1", check_tail="setup exploded"))
    assert len(ps) == 1
    assert ps[0]["fingerprint"] == hashlib.sha1(b"lanectl:train-1").hexdigest()
    assert "train-1" in ps[0]["summary"]


def test_proposals_count_and_window():
    evs = [train("train-1", check_tail=TAIL, ts="2026-11-08T10:00:00Z"),
           train("train-2", check_tail=TAIL, ts="2026-11-08T12:00:00Z")]
    ps = [p for e in evs for p in from_train(e)]
    out = proposals([make_event("triage.proposed", p, ts=ts)
                     for p, ts in zip(ps, ["2026-11-08T10:00:00Z"] * 2
                                      + ["2026-11-08T12:00:00Z"] * 2)])
    assert len(out) == 2
    assert all(p["count"] == 2 for p in out)
    assert out[0]["first_ts"] == "2026-11-08T10:00:00Z"
    assert out[0]["last_ts"] == "2026-11-08T12:00:00Z"


def test_scan_requires_record_to_mark_scanned(tmp_path, monkeypatch):
    monkeypatch.setenv("LANECTL_STATE", str(tmp_path))
    log = EventLog()
    log.append("train.built", train("train-1", check_tail=TAIL)["data"])
    assert len(scan(log, record=False)) == 2
    assert [e for e in log.read() if e["type"] == "triage.proposed"] == []
    assert len(scan(log, record=True)) == 2
    assert scan(log, record=False) == []
    assert unscanned(log.read()) == []


def test_cli_scan_and_list(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LANECTL_STATE", str(tmp_path))
    EventLog().append("train.built", train("train-1", check_tail=TAIL)["data"])
    assert cli.main(["triage", "scan", "--record"]) == 0
    assert "2 proposal(s) recorded" in capsys.readouterr().out
    assert cli.main(["triage"]) == 0
    out = capsys.readouterr().out
    assert "tests/a.py::test_one" in out and "1x" in out
