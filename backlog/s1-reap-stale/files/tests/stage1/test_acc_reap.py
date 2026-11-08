"""Acceptance: abandoned attempts are closed so admission and caps recover (planner-owned)."""
from datetime import datetime, timedelta, timezone

from lanectl.events import EventLog, project_items
from lanectl.reap import reap


def _claim(log, item, n):
    log.append("release.published", {"release_id": item, "revision": 1}, item_id=item)
    log.append("item.claimed", {"attempt_id": f"{item}-a{n}", "lane": "implement", "model": "m",
                                "worker": "w", "release_revision": 1}, item_id=item)


def test_reap_closes_only_stale_open_attempts(tmp_path):
    log = EventLog(tmp_path / "e.jsonl")
    _claim(log, "old", 1)
    _claim(log, "done", 1)
    log.append("attempt.finished", {"attempt_id": "done-a1", "outcome": "done", "exit_code": 0,
                                    "head_sha": "h"}, item_id="done")
    later = datetime.now(timezone.utc) + timedelta(hours=2)

    assert reap(log, now=datetime.now(timezone.utc), older_than_s=3600, max_attempts=2) == []
    closed = reap(log, now=later, older_than_s=3600, max_attempts=2)
    assert closed == ["old-a1"]
    items = project_items(log.read())
    assert items["old"].state == "requeued"
    assert items["done"].state == "implemented"
    types = [e["type"] for e in log.read() if e["item_id"] == "old"]
    assert types[-4:] == ["attempt.finished", "decision.recorded", "experiment.recorded", "item.requeued"]
    fin = [e for e in log.read() if e["type"] == "attempt.finished" and e["item_id"] == "old"][0]["data"]
    assert fin["outcome"] == "failed" and fin["exit_code"] == -1
    assert reap(log, now=later, older_than_s=3600, max_attempts=2) == []   # idempotent


def test_reap_parks_when_attempts_exhausted(tmp_path):
    log = EventLog(tmp_path / "e.jsonl")
    _claim(log, "x", 1)
    later = datetime.now(timezone.utc) + timedelta(hours=2)
    reap(log, now=later, older_than_s=60, max_attempts=1)
    assert project_items(log.read())["x"].state == "parked"


def test_cli_reap_help():
    import pytest
    from lanectl import cli
    with pytest.raises(SystemExit) as exc:
        cli.main(["reap", "--help"])
    assert exc.value.code == 0
