"""lanectl lanes: cap usage is scoped to the lane and to the UTC day."""
import json
from datetime import datetime, timedelta, timezone

from lanectl import cli, events
from lanectl.config import home

CLAIM = {"model": "scripted/model", "worker": "scripted"}


def _add_lane(name: str) -> None:
    src = home() / "governance" / "lanes" / "implement.toml"
    text = src.read_text().replace('lane = "implement"', f'lane = "{name}"')
    (home() / "governance" / "lanes" / f"{name}.toml").write_text(text)


def _append_yesterday(log, etype: str, data: dict, item_id: str) -> None:
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    ev = events.make_event(etype, data, item_id=item_id, ts=yesterday.strftime("%Y-%m-%dT%H:%M:%SZ"))
    with open(log.path, "a") as fh:
        fh.write(json.dumps(ev, sort_keys=True) + "\n")


def test_usage_is_per_lane_and_per_utc_day(estate, capsys):
    _, release, log = estate
    _add_lane("review")
    for item in ("aa-open", "bb-cand", "cc-old"):
        release(item, "def test_ok():\n    assert True\n")
    log.append("item.claimed", dict(CLAIM, lane="implement", attempt_id="aa-open-a1"), item_id="aa-open")
    log.append("item.claimed", dict(CLAIM, lane="review", attempt_id="bb-cand-a1"), item_id="bb-cand")
    log.append("attempt.finished", {"attempt_id": "bb-cand-a1", "outcome": "done", "exit_code": 0,
                                    "head_sha": "0" * 40}, item_id="bb-cand")
    log.append("decision.recorded", {"attempt_id": "bb-cand-a1", "decision": "candidate",
                                     "reasons": [], "rules_revision": 1}, item_id="bb-cand")
    _append_yesterday(log, "item.claimed", dict(CLAIM, lane="review", attempt_id="cc-old-a1"),
                      item_id="cc-old")

    assert cli.main(["lanes", "--json"]) == 0
    rows = {r["lane"]: r for r in json.loads(capsys.readouterr().out)}
    assert rows["implement"]["caps"]["concurrency"]["used"] == 1
    assert rows["implement"]["caps"]["items_per_day"]["used"] == 1
    assert rows["implement"]["caps"]["accepted_unlanded_max"]["used"] == 0
    # review: one claim today and one yesterday; one candidate; cc-old still claimed.
    assert rows["review"]["caps"]["items_per_day"]["used"] == 1
    assert rows["review"]["caps"]["accepted_unlanded_max"]["used"] == 1
    assert rows["review"]["caps"]["concurrency"]["used"] == 1
    assert rows["review"]["routing"] == {"scripted/model": 1.0}

    assert cli.main(["lanes"]) == 0
    out = capsys.readouterr().out
    assert "implement" in out and "review" in out
    assert "  routing: scripted/model=1.0" in out
