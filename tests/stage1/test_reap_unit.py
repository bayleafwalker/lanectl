"""Unit coverage for reaping beyond the planner's acceptance file."""
from datetime import datetime, timedelta, timezone

from lanectl.events import EventLog, project_items
from lanectl.reap import reap


def _claim(log, item, n, **extra):
    log.append("release.published", {"release_id": item, "revision": 1}, item_id=item)
    log.append("item.claimed", {"attempt_id": f"{item}-a{n}", "lane": "implement",
                                "model": "m", "worker": "w", "release_revision": 1,
                                **extra}, item_id=item)


def test_reap_closes_in_claim_order_and_parks_when_budget_is_spent(tmp_path):
    log = EventLog(tmp_path / "e.jsonl")
    _claim(log, "item", 1)
    _claim(log, "item", 2)
    later = datetime.now(timezone.utc) + timedelta(hours=2)

    assert reap(log, now=later, older_than_s=60, max_attempts=2) == ["item-a1", "item-a2"]
    assert project_items(log.read())["item"].state == "parked"
    types = [e["type"] for e in log.read() if e["item_id"] == "item"]
    assert types[-8:] == ["attempt.finished", "decision.recorded", "experiment.recorded",
                          "item.requeued", "attempt.finished", "decision.recorded",
                          "experiment.recorded", "item.parked"]


def test_fresh_claims_are_left_alone_and_fields_are_copied(tmp_path):
    log = EventLog(tmp_path / "e.jsonl")
    _claim(log, "item", 1, task_class="recovery")
    before = len(log.read())

    soon = datetime.now(timezone.utc) + timedelta(seconds=5)
    assert reap(log, now=soon, older_than_s=60, max_attempts=3) == []
    assert len(log.read()) == before

    later = datetime.now(timezone.utc) + timedelta(hours=1)
    assert reap(log, now=later, older_than_s=60, max_attempts=3) == ["item-a1"]
    exp = next(e for e in log.read() if e["type"] == "experiment.recorded")["data"]
    assert exp["model"] == "m" and exp["worker"] == "w"
    assert exp["task_class"] == "recovery" and exp["decision"] == "rejected"
    assert exp["elapsed_s"] > 60
    assert project_items(log.read())["item"].state == "requeued"
