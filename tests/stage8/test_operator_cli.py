"""Operator-interface contract: grouped help, status as home, errors, effects, --json."""
import json

import pytest

from lanectl import cli, doctor, render

ACC = "def test_ok():\n    assert True\n"


def _seed(estate):
    _, release, log = estate
    for item in ("aa-open", "bb-parked"):
        release(item, ACC)
    log.append("release.published", {"release_id": "bb-parked", "revision": 1}, item_id="bb-parked")
    log.append("item.parked", {"reason": "needs review"}, item_id="bb-parked")
    return log


def test_bare_lanectl_prints_grouped_help_and_exits_zero(capsys):
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    assert "Start here:" in out and "Examples:" in out and "lanectl <command> --help" in out


def test_every_command_is_in_a_help_group():
    _, sub, _ = cli._build_parser()
    listed = {n for _, cmds in cli.GROUPS for n, _ in cmds}
    assert set(sub.choices) <= listed


def test_version(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0 and capsys.readouterr().out.startswith("lanectl ")


def test_misspelled_command_suggests(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["stauts"])
    assert e.value.code == 2 and "did you mean status?" in capsys.readouterr().err


def test_status_sections_next_and_bounded(estate, capsys):
    _seed(estate)
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert len(lines) <= 24 and not any(l.lstrip().startswith("{") for l in lines)
    assert "NEEDS YOU (1)" in out and "bb-parked" in out
    assert "next: lanectl backlog show bb-parked" in out


def test_status_never_calls_a_blocked_release_ready(estate, capsys):
    _, release, log = estate
    release("cc-draft", ACC)   # not published to the log; make it a draft
    import os
    from pathlib import Path
    toml = Path(os.environ["LANECTL_HOME"]) / "backlog" / "cc-draft" / "release.toml"
    toml.write_text(toml.read_text() + "\ndraft = true\n")
    cli.main(["ready"])
    ready_out = capsys.readouterr().out
    cli.main(["status", "--json"])
    doc = json.loads(capsys.readouterr().out)
    if "BLOCKED  cc-draft" in ready_out:
        assert [b["id"] for b in doc["blocked"]] == ["cc-draft"]
        assert doc["blocked"][0]["fix"] == "lanectl backlog show cc-draft"
        assert doc["counts"].get("ready", 0) == 0


def test_status_json_schema_and_metrics(estate, capsys):
    _seed(estate)
    assert cli.main(["status", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["schema"] == "lanectl.status/v1" and "metrics" in doc
    assert doc["needs_you"][0]["id"] == "bb-parked"


@pytest.mark.parametrize("argv", (["status"], ["backlog", "list"]))
def test_missing_home_is_an_error_naming_the_fix(argv, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LANECTL_HOME", str(tmp_path / "nope"))
    assert cli.main(argv) == 3
    err = capsys.readouterr().err
    assert err.startswith("error:") and str(tmp_path / "nope") in err and "fix:" in err


@pytest.mark.parametrize("cmd", ("ready", "candidates", "events"))
def test_json_objects_have_a_schema(cmd, estate, capsys):
    _seed(estate)
    assert cli.main([cmd, "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["schema"] == f"lanectl.{cmd}/v1"


def test_doctor_collapses_repeats_and_summarises():
    f = [doctor.Finding(doctor.OK, "home", "x"),
         *(doctor.Finding(doctor.WARN, "base-drift", f"r{i}: drift", subject=f"r{i}") for i in range(3))]
    out = doctor.collapse(f)
    assert len(out) == 2 and "3 x" in out[1].detail and out[1].fix == "lanectl backlog rebase --pending"
    assert doctor.summary(out) == "1 ok, 1 warn, 0 error"


def test_reject_dry_run_changes_nothing_and_acts_without_it(estate, capsys):
    log = _seed(estate)
    before = len(log.read())
    assert cli.main(["reject", "x-a1", "why", "--dry-run"]) == 0
    assert "would requeue" in capsys.readouterr().out and len(log.read()) == before
    assert cli.main(["reject", "nope-a1", "why"]) == 3   # unknown attempt: not found, receipt line
    assert "next: lanectl status" in capsys.readouterr().out


def test_reap_dry_run_and_receipt(estate, capsys):
    log = _seed(estate)
    before = len(log.read())
    assert cli.main(["reap", "--dry-run"]) == 0
    assert len(log.read()) == before and "would examine" in capsys.readouterr().out
    assert cli.main(["reap", "--yes"]) == 0
    assert "next: lanectl status" in capsys.readouterr().out


def test_render_helpers():
    assert render.money(0.5718741899999997) == "$0.57"
    assert render.count(2_700_000) == "2.7M" and render.count(940) == "940"
    assert render.clip("a" * 10, 5) == "aaaa…"


def test_doctor_text_ends_with_summary_line(estate, capsys):
    _, release, _ = estate
    release("aa-fine", ACC)
    assert cli.main(["doctor"]) == 0
    last = capsys.readouterr().out.splitlines()[-1]
    assert last.split()[1] == "summary:" and " ok, " in last and " warn, " in last
