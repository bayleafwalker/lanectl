"""Extra coverage: expected-failure shapes and the recorded publish override."""
import os
import tomllib
from pathlib import Path

from lanectl import cli
from lanectl.config import load_release
from lanectl.lint_release import classify_failure

HEAD = "_____________________________ test_{name} _____________________________\n"
TAIL = "=========================== short test summary info ============================\n"


def _run(*sections):
    return "".join(sections) + TAIL + f"{len(sections)} failed in 0.10s\n"


def _did_not_raise(name, exc):
    return HEAD.format(name=name) + (
        f"    def test_{name}():\n>       with pytest.raises({exc}):\n"
        f"E       Failed: DID NOT RAISE <class '{exc}'>\n"
        f"tests/test_x.py:9: Failed\n")


def test_did_not_raise_is_expected_for_any_named_exception():
    assert classify_failure(_run(_did_not_raise("aa", "ValueError"))) == "expected"


def test_quoted_key_error_is_expected_but_bare_key_error_is_not():
    quoted = _run(HEAD.format(name="bb") + (
        ">       assert row[\"infra_attempts\"] == 2\n"
        "E       KeyError: 'infra_attempts'\n"
        "tests/test_x.py:12: KeyError\n"))
    assert classify_failure(quoted) == "expected"
    # An unquoted key is an unknown shape, not a missing product field.
    assert classify_failure(_run(HEAD.format(name="ff") + "E   KeyError: 0\n")) == "spec-gap"


def test_raised_contract_error_stays_spec_gap_in_both_shapes():
    pytest_style = _run(HEAD.format(name="cc") + (
        ">       load_release(d)\n"
        "E       lanectl.contracts.ContractError: bad size 'XL'\n"
        "tests/test_x.py:15: ContractError\n"))
    traceback_style = _run(HEAD.format(name="cc") + (
        "Traceback (most recent call last):\n"
        "  File \"src/lanectl/config.py\", line 9, in load_release\n"
        "lanectl.contracts.ContractError: bad size 'XL'\n"))
    assert classify_failure(pytest_style) == "spec-gap"
    assert classify_failure(traceback_style) == "spec-gap"
    # The same class only named by pytest.raises is a missing feature, not a gap.
    assert classify_failure(_run(_did_not_raise("aa", "ContractError"))) == "expected"


def test_name_error_stays_spec_gap():
    raised = _run(HEAD.format(name="ee") + "E   NameError: name 'helper' is not defined\n")
    assert classify_failure(raised) == "spec-gap"
    assert classify_failure(_run(_did_not_raise("ee", "NameError"))) == "expected"


ACC = "def test_ok():\n    assert True\n"
CONTRACT = ("from lanectl.contracts import ContractError\n\n"
            "def test_bad():\n    raise ContractError(\"bad id\")\n")
NEW = ["backlog", "new", "aa-new", "--repo", "target", "--title", "Add mul", "--size", "S",
       "--class", "glue", "--scope", "src/**", "--test", "tests/test_acc_mul.py"]
NEW_TWO = ["backlog", "new", "aa-two", "--repo", "target", "--title", "Add div", "--size", "S",
           "--class", "glue", "--scope", "src/**", "--test", "tests/test_acc_two.py"]


def _scaffold(capsys, argv=NEW, item="aa-new"):
    assert cli.main(argv) == 0
    capsys.readouterr()
    return Path(os.environ["LANECTL_HOME"]) / "backlog" / item


def _edit_outcome(toml: Path) -> None:
    raw = tomllib.loads(toml.read_text())
    toml.write_text(toml.read_text().replace(raw["outcome"], "Add mul."))


def _record_override(toml: Path, text: str) -> None:
    toml.write_text(toml.read_text() + f'\n[lint]\noverride = "{text}"\n')


def test_publish_override_prints_every_problem(estate, capsys):
    d = _scaffold(capsys)
    (d / "files" / "tests" / "test_acc_mul.py").write_text(ACC)
    (d / "files" / "tests" / "test_acc_bad.py").write_text(CONTRACT)
    toml = d / "release.toml"
    _edit_outcome(toml)
    toml.write_text(toml.read_text().replace(
        'files = ["tests/test_acc_mul.py"]',
        'files = ["tests/test_acc_mul.py", "tests/test_acc_bad.py"]'))
    _record_override(toml, "planner: missing key, override recorded")

    assert cli.main(["backlog", "publish", "aa-new"]) == 0
    out = capsys.readouterr().out
    assert "passes-on-base" in out
    assert "spec-gap" in out
    assert "lint override: planner: missing key, override recorded" in out
    assert load_release(d).draft is False


def test_publish_override_does_not_bypass_todo_stub_or_absent_table(estate, capsys):
    d = _scaffold(capsys)
    toml = d / "release.toml"
    _record_override(toml, "planner: missing key")
    # A TODO outcome is still refused, override or not.
    assert cli.main(["backlog", "publish", "aa-new"]) == 1
    assert load_release(d).draft is True
    # So is a stub test.
    _edit_outcome(toml)
    assert cli.main(["backlog", "publish", "aa-new"]) == 1
    assert load_release(d).draft is True
    # A real test that passes on base is published on the recorded override.
    (d / "files" / "tests" / "test_acc_mul.py").write_text(ACC)
    assert cli.main(["backlog", "publish", "aa-new"]) == 0
    out = capsys.readouterr().out
    assert "passes-on-base" in out
    assert "lint override: planner: missing key" in out
    assert load_release(d).draft is False
    # Without the [lint] table publish is unchanged: problems still refuse.
    d2 = _scaffold(capsys, NEW_TWO, "aa-two")
    (d2 / "files" / "tests" / "test_acc_two.py").write_text(ACC)
    _edit_outcome(d2 / "release.toml")
    assert cli.main(["backlog", "publish", "aa-two"]) == 1
    out = capsys.readouterr().out
    assert "passes-on-base" in out
    assert "lint override" not in out
    assert load_release(d2).draft is True
