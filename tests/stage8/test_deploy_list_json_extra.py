"""Deploy list: --json is always JSON, including when no deploy is live."""
import json

from lanectl import cli

FUTURE = "2026-11-10T13:00:00Z"


def _deployed(log, train_id, expires_at):
    log.append("train.deployed", {"train_id": train_id, "repo": "target", "passed": True,
                                  "namespace": f"lane-dev-{train_id}",
                                  "expires_at": expires_at})


def test_json_with_no_live_deploys_is_empty_list(estate, capsys):
    assert cli.main(["deploy", "list", "--json"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out) == []
    assert "no live deploys" not in out


def test_json_with_live_deploys_is_the_list(estate, capsys):
    _deployed(estate[2], "train-aa", FUTURE)
    assert cli.main(["deploy", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == [
        {"train_id": "train-aa", "namespace": "lane-dev-train-aa", "repo": "target",
         "expires_at": FUTURE, "expired": False},
    ]


def test_text_form_still_says_no_live_deploys(estate, capsys):
    assert cli.main(["deploy", "list"]) == 0
    assert capsys.readouterr().out.strip() == "no live deploys"


def test_text_form_with_live_deploys_is_unchanged(estate, capsys):
    _deployed(estate[2], "train-aa", FUTURE)
    assert cli.main(["deploy", "list"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        f"lane-dev-train-aa  train-aa  target  expires {FUTURE}",
    ]
