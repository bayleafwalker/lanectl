"""Acceptance: lanectl lanes (planner-owned)."""
import json

from lanectl import cli
from lanectl.config import load_lane

ACC = "def test_ok():\n    assert True\n"
CLAIM = {"lane": "implement", "model": "scripted/model", "worker": "scripted"}


def _seed(estate):
    _, release, log = estate
    for item in ("aa-open", "bb-cand"):
        release(item, ACC)
    log.append("item.claimed", dict(CLAIM, attempt_id="aa-open-a1"), item_id="aa-open")
    log.append("item.claimed", dict(CLAIM, attempt_id="bb-cand-a1"), item_id="bb-cand")
    log.append("attempt.finished", {"attempt_id": "bb-cand-a1", "outcome": "done", "exit_code": 0,
                                    "head_sha": "0" * 40}, item_id="bb-cand")
    log.append("decision.recorded", {"attempt_id": "bb-cand-a1", "decision": "candidate", "reasons": [],
                                     "rules_revision": 1}, item_id="bb-cand")


def test_text_shows_routing_and_cap_usage(estate, capsys):
    _seed(estate)
    lane = load_lane("implement")
    assert cli.main(["lanes"]) == 0
    out = capsys.readouterr().out
    assert "implement" in out and f"r{lane.revision}" in out
    assert "scripted/model=1.0" in out
    assert f"concurrency 1/{lane.caps['concurrency']}" in out
    assert f"items_per_day 2/{lane.caps['items_per_day']}" in out
    assert f"accepted_unlanded_max 1/{lane.caps['accepted_unlanded_max']}" in out
    assert f"size_max={lane.size_max}" in out and f"max_attempts={lane.max_attempts}" in out


def test_json_shape(estate, capsys):
    _seed(estate)
    lane = load_lane("implement")
    assert cli.main(["lanes", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    row = next(r for r in rows if r["lane"] == "implement")
    assert row["revision"] == lane.revision and row["routing"] == {"scripted/model": 1.0}
    assert row["caps"]["concurrency"] == {"used": 1, "limit": lane.caps["concurrency"]}
    assert row["caps"]["items_per_day"] == {"used": 2, "limit": lane.caps["items_per_day"]}
    assert row["caps"]["accepted_unlanded_max"] == {"used": 1, "limit": lane.caps["accepted_unlanded_max"]}


def test_empty_log_uses_nothing(estate, capsys):
    assert cli.main(["lanes", "--json"]) == 0
    row = json.loads(capsys.readouterr().out)[0]
    assert all(v["used"] == 0 for v in row["caps"].values())
