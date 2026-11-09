"""Acceptance: lane.decision records for dispatch, rerun and escalation (planner-owned)."""
import json
import os
import time
from pathlib import Path

from lanectl import runner
from lanectl.events import EventLog
from tests.seed.test_end_to_end import SUB_TEST, scripted  # estate comes from tests/stage7/conftest.py

ADD_TEST = "from calc import add\n\ndef test_add_neg():\n    assert add(-1, -1) == -2\n"


def good(wt):
    (wt / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
    (wt / "tests" / "test_sub_extra.py").write_text("from calc import sub\n\ndef test_neg():\n    assert sub(1, 2) == -1\n")


def wrong(wt):
    (wt / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return b - a\n")
    (wt / "tests" / "test_sub_extra.py").write_text("from calc import sub\n\ndef test_neg():\n    assert sub(2, 1) == -1\n")


def _decisions(log, **match):
    out = [e for e in log.read() if e["type"] == "lane.decision"]
    return [e for e in out if all(e["data"].get(k) == v for k, v in match.items())]


def _one(xs):
    assert len(xs) == 1, f"expected one lane.decision, got {len(xs)}"
    return xs[0]


def test_claim_records_proposed_then_applied(estate):
    repo, release, log = estate
    release("add-sub", SUB_TEST)
    c = runner.admit("implement", log)
    prop = _one(_decisions(log, kind="dispatch", phase="proposed"))
    appl = _one(_decisions(log, kind="dispatch", phase="applied"))
    for e in (prop, appl):
        d = e["data"]
        assert e["item_id"] == "add-sub" and d["chosen"] == c.model == "scripted/model"
        assert d["mechanism"] == "weighted-hash/v1" and d["policy_revision"].startswith("lane/implement@")
        assert d["subject"] == {"item_id": "add-sub", "attempt_id": c.attempt_id}
        assert d["alternatives"] == {"scripted/model": 1.0} and d["probabilities"] == {"scripted/model": 1.0}
        assert any(b.startswith("release:add-sub@") for b in d["basis"]) and d["snapshot_ts"].endswith("Z")
    assert appl["data"]["proposal_id"] == prop["data"]["decision_id"] != appl["data"]["decision_id"]
    assert prop["data"]["cycle_id"] == appl["data"]["cycle_id"]


def test_cap_block_records_refusal(estate):
    repo, release, log = estate
    lane = Path(os.environ["LANECTL_HOME"]) / "governance" / "lanes" / "implement.toml"
    lane.write_text(lane.read_text().replace("concurrency = 3", "concurrency = 1"))
    release("add-sub", SUB_TEST)
    release("add-neg", ADD_TEST)
    runner.admit("implement", log)
    out = runner.admit("implement", log)
    assert isinstance(out, str) and out.startswith("cap: concurrency")
    ref = _one(_decisions(log, phase="refused"))
    d = ref["data"]
    assert d["kind"] == "dispatch" and d["chosen"] is None and d["mechanism"] == "static-caps/v1"
    assert d["reasons"][0].startswith("cap: concurrency") and d["cycle_id"]
    cycles = {e["data"]["cycle_id"] for e in _decisions(log)}
    assert len(cycles) == 2


def test_requeue_and_park_record_rerun_and_escalation(estate):
    repo, release, log = estate
    release("add-sub", SUB_TEST)
    c1 = runner.admit("implement", log)
    assert "-> rejected" in runner.execute(c1, log, adapter_fn=scripted(wrong))
    rerun = _one(_decisions(log, kind="rerun"))
    assert rerun["data"]["phase"] == "applied" and rerun["data"]["chosen"] == "requeue"
    assert rerun["data"]["subject"]["attempt_id"] == c1.attempt_id and rerun["data"]["reasons"]
    c2 = runner.admit("implement", log)
    runner.execute(c2, log, adapter_fn=scripted(wrong))
    esc = _one(_decisions(log, kind="escalation"))
    assert esc["data"]["chosen"] == "park" and esc["data"]["subject"]["attempt_id"] == c2.attempt_id


def test_records_stay_small_and_cheap(estate, tmp_path):
    repo, release, log = estate
    release("add-sub", SUB_TEST)
    c = runner.admit("implement", log)
    runner.execute(c, log, adapter_fn=scripted(good))
    lines = [line for line in Path(log.path).read_text().splitlines() if '"lane.decision"' in line]
    assert lines and all(len(line.encode()) <= 2048 for line in lines)
    sample = json.loads(lines[-1])
    bench = EventLog(tmp_path / "bench.jsonl")
    took = []
    for _ in range(100):
        t = time.perf_counter()
        bench.append("lane.decision", sample["data"], item_id=sample["item_id"])
        took.append(time.perf_counter() - t)
    took.sort()
    assert took[94] <= 0.025        # regression guard; budget 10 ms p95 (measured 5.9 ms)
