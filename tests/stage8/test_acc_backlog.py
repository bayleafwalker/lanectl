"""Acceptance: backlog list and show (planner-owned)."""
import json

from lanectl import cli
from lanectl.backlog import backlog_rows
from lanectl.config import load_releases

ACC = "def test_ok():\n    assert True\n"
CLAIM = {"lane": "implement", "model": "scripted/model", "worker": "scripted"}


def _seed(estate):
    _, release, log = estate
    for item in ("aa-landed", "bb-parked", "cc-new"):
        release(item, ACC)
    log.append("release.published", {"release_id": "aa-landed", "revision": 1}, item_id="aa-landed")
    log.append("item.claimed", dict(CLAIM, attempt_id="aa-landed-a1"), item_id="aa-landed")
    log.append("item.landed", {"attempt_id": "aa-landed-a1", "train_id": "tt", "fix_commits": []},
               item_id="aa-landed")
    log.append("release.published", {"release_id": "bb-parked", "revision": 1}, item_id="bb-parked")
    log.append("item.claimed", dict(CLAIM, attempt_id="bb-parked-a1"), item_id="bb-parked")
    log.append("item.parked", {"reason": "escalated: spec unclear"}, item_id="bb-parked")
    return log


def test_rows_carry_state_tries_and_reason(estate):
    log = _seed(estate)
    rows = backlog_rows(load_releases(), log.read())
    assert [r["id"] for r in rows] == ["aa-landed", "bb-parked", "cc-new"]
    by = {r["id"]: r for r in rows}
    assert by["aa-landed"]["state"] == "landed" and by["aa-landed"]["tries"] == 1
    assert by["bb-parked"]["state"] == "parked" and "spec unclear" in by["bb-parked"]["last_reason"]
    assert by["cc-new"]["state"] == "new" and by["cc-new"]["tries"] == 0
    for r in rows:
        assert {"repo", "title", "task_class", "size", "revision", "published"} <= set(r)
    assert by["aa-landed"]["published"] == 1 and by["cc-new"]["published"] == 0


def test_list_prints_every_release_and_a_summary(estate, capsys):
    _seed(estate)
    assert cli.main(["backlog", "list"]) == 0
    out = capsys.readouterr().out
    for item in ("aa-landed", "bb-parked", "cc-new"):
        assert item in out
    assert "3 releases" in out
    assert "landed=1" in out and "parked=1" in out and "new=1" in out


def test_list_open_hides_landed(estate, capsys):
    _seed(estate)
    assert cli.main(["backlog", "list", "--open"]) == 0
    out = capsys.readouterr().out
    assert "aa-landed" not in out and "bb-parked" in out and "cc-new" in out


def test_list_state_filter_as_json(estate, capsys):
    _seed(estate)
    assert cli.main(["backlog", "list", "--state", "parked", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in rows] == ["bb-parked"] and rows[0]["state"] == "parked"


def test_show_lists_release_and_attempts(estate, capsys):
    _seed(estate)
    assert cli.main(["backlog", "show", "bb-parked"]) == 0
    out = capsys.readouterr().out
    for text in ("bb-parked-a1", "scripted/model", "spec unclear", "target", "implement it", "glue"):
        assert text in out


def test_show_unknown_release_exits_2(estate, capsys):
    _seed(estate)
    assert cli.main(["backlog", "show", "zz-missing"]) == 2
    assert "unknown release" in capsys.readouterr().err
