"""Acceptance: s3-deploy-list-json - deploy list --json is always JSON."""
import json

from lanectl import cli


def test_json_list_is_empty_list_when_nothing_live(estate, capsys):
    assert cli.main(["deploy", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_text_form_unchanged(estate, capsys):
    assert cli.main(["deploy", "list"]) == 0
    assert capsys.readouterr().out.strip() == "no live deploys"
