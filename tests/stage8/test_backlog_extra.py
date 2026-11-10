"""Extra coverage: filters, JSON purity, published revisions and show details."""
import json

from lanectl import cli
from lanectl.backlog import backlog_rows
from lanectl.config import load_releases

ACC = "def test_ok():\n    assert True\n"
CLAIM = {"lane": "implement", "model": "scripted/model", "worker": "scripted"}


def test_rows_take_highest_published_revision(estate):
    _, release, log = estate
    release("aa-landed", ACC)
    log.append("release.published", {"release_id": "aa-landed", "revision": 1}, item_id="aa-landed")
    log.append("release.published", {"release_id": "aa-landed", "revision": 3}, item_id="aa-landed")
    row = backlog_rows(load_releases(), log.read())[0]
    assert row["published"] == 3 and row["revision"] == 1


def test_list_repeated_states_and_repo_filter(estate, capsys):
    _, release, log = estate
    release("aa-landed", ACC)
    release("bb-parked", ACC)
    log.append("item.claimed", dict(CLAIM, attempt_id="aa-landed-a1"), item_id="aa-landed")
    log.append("item.landed", {"attempt_id": "aa-landed-a1", "train_id": "tt", "fix_commits": []},
               item_id="aa-landed")
    assert cli.main(["backlog", "list", "--state", "landed", "--state", "new", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in rows] == ["aa-landed", "bb-parked"]
    assert cli.main(["backlog", "list", "--repo", "other", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_show_open_attempt_uses_item_state(estate, capsys):
    _, release, log = estate
    release("cc-running", ACC)
    log.append("item.claimed", dict(CLAIM, attempt_id="cc-running-a1"), item_id="cc-running")
    assert cli.main(["backlog", "show", "cc-running"]) == 0
    out = capsys.readouterr().out
    assert "cc-running-a1" in out and "scripted/model" in out and "claimed" in out


def test_show_prints_attempt_decision_and_reason(estate, capsys):
    _, release, log = estate
    release("dd-rejected", ACC)
    log.append("item.claimed", dict(CLAIM, attempt_id="dd-rejected-a1"), item_id="dd-rejected")
    log.append("decision.recorded",
               {"attempt_id": "dd-rejected-a1", "decision": "rejected",
                "reasons": ["acceptance: failed"], "rules_revision": 1},
               item_id="dd-rejected")
    assert cli.main(["backlog", "show", "dd-rejected"]) == 0
    out = capsys.readouterr().out
    assert "dd-rejected-a1" in out and "rejected" in out and "acceptance: failed" in out
