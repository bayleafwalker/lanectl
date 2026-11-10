"""Acceptance: s3-lint-expected - lint classifies missing-feature failures; publish overrides."""
import os
import tomllib
from pathlib import Path

from lanectl import cli
from lanectl.config import load_release
from lanectl.lint_release import classify_failure

HEAD = "_____________________________ test_{name} _____________________________\n"

DID_NOT_RAISE = HEAD.format(name="aa") + (
    "    def test_aa(tmp_path):\n>       with pytest.raises(ContractError, match=\"target\"):\n"
    "E       Failed: DID NOT RAISE <class 'lanectl.contracts.ContractError'>\n"
    "tests/stage8/test_x.py:9: Failed\n")
KEY_ERROR = HEAD.format(name="bb") + (
    ">       assert row[\"infra_attempts\"] == 2\nE       KeyError: 'infra_attempts'\n"
    "tests/stage8/test_x.py:12: KeyError\n")
RAISED_CONTRACT = HEAD.format(name="cc") + (
    ">       load_release(d)\nE       lanectl.contracts.ContractError: bad size 'XL'\n"
    "tests/stage8/test_x.py:15: ContractError\n")
SYNTAX = HEAD.format(name="dd") + "E     SyntaxError: invalid syntax\n"
TAIL = "=========================== short test summary info ============================\n"


def _run(*sections, failed=None):
    n = failed if failed is not None else len(sections)
    return "".join(sections) + TAIL + f"{n} failed in 0.10s\n"


def test_did_not_raise_is_expected():
    assert classify_failure(_run(DID_NOT_RAISE)) == "expected"


def test_quoted_key_error_is_expected():
    assert classify_failure(_run(KEY_ERROR)) == "expected"


def test_mixed_missing_feature_sections_are_expected():
    assert classify_failure(_run(DID_NOT_RAISE, KEY_ERROR)) == "expected"


def test_raised_contract_error_stays_spec_gap():
    assert classify_failure(_run(RAISED_CONTRACT)) == "spec-gap"
    assert classify_failure(_run(DID_NOT_RAISE, RAISED_CONTRACT)) == "spec-gap"


def test_syntax_error_stays_spec_gap():
    assert classify_failure(_run(SYNTAX)) == "spec-gap"


ACC = "def test_ok():\n    assert True\n"
NEW = ["backlog", "new", "aa-new", "--repo", "target", "--title", "Add mul", "--size", "S",
       "--class", "glue", "--scope", "src/**", "--test", "tests/test_acc_mul.py"]


def _passing_draft():
    d = Path(os.environ["LANECTL_HOME"]) / "backlog" / "aa-new"
    (d / "files" / "tests" / "test_acc_mul.py").write_text(ACC)          # passes on base
    toml = d / "release.toml"
    raw = tomllib.loads(toml.read_text())
    toml.write_text(toml.read_text().replace(raw["outcome"], "Add mul."))
    return d, toml


def test_publish_with_override_prints_problems_and_publishes(estate, capsys):
    assert cli.main(NEW) == 0
    d, toml = _passing_draft()
    toml.write_text(toml.read_text() + '\n[lint]\noverride = "base failure is a missing key"\n')
    assert cli.main(["backlog", "publish", "aa-new"]) == 0
    out = capsys.readouterr().out
    assert "passes-on-base" in out
    assert "lint override: base failure is a missing key" in out
    assert load_release(d).draft is False


def test_publish_with_empty_override_still_refuses(estate, capsys):
    assert cli.main(NEW) == 0
    d, toml = _passing_draft()
    toml.write_text(toml.read_text() + '\n[lint]\noverride = ""\n')
    assert cli.main(["backlog", "publish", "aa-new"]) == 1
    assert load_release(d).draft is True
