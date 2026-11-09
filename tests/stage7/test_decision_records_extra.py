"""Extra coverage for lane.decision records beyond the planner acceptance file."""
import json
import os
from pathlib import Path

from lanectl import decisions, runner
from lanectl.adapters import AdapterResult
from lanectl.contracts import LaneRevision
from lanectl.events import EventLog
from tests.seed.test_end_to_end import SUB_TEST, scripted  # estate comes from tests/stage7/conftest.py


def _decisions(log):
    return [e for e in log.read() if e["type"] == "lane.decision"]


def _lane_file() -> Path:
    return Path(os.environ["LANECTL_HOME"]) / "governance" / "lanes" / "implement.toml"


def test_alternatives_are_the_positive_eligible_weights(estate):
    repo, release, log = estate
    lane = _lane_file()
    text = lane.read_text()
    old = 'weights = { "scripted/model" = 1.0 }'
    assert old in text
    lane.write_text(text.replace(
        old, 'weights = { "scripted/model" = 1.0, "scripted/other" = 2.0, "scripted/zero" = 0.0 }'))
    release("alt", SUB_TEST)

    c = runner.admit("implement", log)

    assert not isinstance(c, str), c
    decs = _decisions(log)
    assert [e["data"]["phase"] for e in decs] == ["proposed", "applied"]
    for e in decs:
        d = e["data"]
        assert d["chosen"] in {"scripted/model", "scripted/other"}
        assert d["alternatives"] == {"scripted/model": 1.0, "scripted/other": 2.0}
        assert set(d["probabilities"]) == set(d["alternatives"])
        assert sum(d["probabilities"].values()) == 1.0
        assert d["probabilities"][d["chosen"]] == 1.0
        assert "release:alt@1" in d["basis"]
        assert any(b.startswith("lane:implement@") for b in d["basis"])


def test_empty_cycle_refusal_has_no_item_id(estate):
    repo, release, log = estate

    out = runner.admit("implement", log)

    assert isinstance(out, str) and out.startswith("nothing ready"), out
    records = _decisions(log)
    assert len(records) == 1
    assert records[0]["item_id"] is None
    d = records[0]["data"]
    assert d["phase"] == "refused" and d["chosen"] is None
    assert d["mechanism"] == "static-caps/v1"
    assert d["reasons"] == ["nothing ready"] and d["cycle_id"]


def test_infra_retry_records_a_rerun(estate):
    repo, release, log = estate
    release("infra", SUB_TEST)
    c = runner.admit("implement", log)
    dead = lambda **_: AdapterResult("failed", 1, "", None)

    out = runner.execute(c, log, adapter_fn=dead)

    assert "-> rejected: infra:" in out, out
    rerun = [e for e in _decisions(log) if e["data"]["kind"] == "rerun"]
    assert len(rerun) == 1
    d = rerun[0]["data"]
    assert d["phase"] == "applied" and d["chosen"] == "requeue"
    assert d["mechanism"] == "gates"
    assert d["subject"] == {"item_id": "infra", "attempt_id": c.attempt_id}
    assert d["reasons"] and d["reasons"][0].startswith("infra:")


def test_long_reasons_stay_within_the_record_budget(tmp_path):
    lane = LaneRevision("implement", 1, "M", {"m": 1.0}, 2, "different_model", {}, {},
                        (), (), (), (), ())
    log = EventLog(tmp_path / "events.jsonl")

    decisions.refused(log, lane=lane, cycle_id="cyc-test", item_id="it-1",
                      reasons=[f"reason {n}: " + "x" * 900 for n in range(20)])

    line = Path(log.path).read_text().splitlines()[0]
    assert len(line.encode()) <= decisions.MAX_RECORD_BYTES
    data = json.loads(line)["data"]
    assert data["phase"] == "refused" and data["reasons"]
