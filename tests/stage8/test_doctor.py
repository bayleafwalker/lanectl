"""Doctor checks beyond the acceptance path: failing governance surface and edge cases."""
import json
import os
import re
import subprocess
from pathlib import Path

from lanectl import cli
from lanectl.contracts import make_event

ACC = "def test_ok():\n    assert True\n"
LINE = re.compile(r"^(OK|WARN|ERROR)\s+[\w-]+: \S")


def _home():
    return Path(os.environ["LANECTL_HOME"])


def _lines(capsys):
    return capsys.readouterr().out.splitlines()


def _commit(repo: Path, name: str) -> None:
    (repo / name).write_text("x\n")
    for cmd in (["add", "-A"], ["commit", "-qm", name]):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *cmd],
                       cwd=repo, check=True)


def test_every_line_is_level_check_detail(estate, capsys):
    _, release, _ = estate
    release("aa-fine", ACC)
    assert cli.main(["doctor"]) == 0
    lines = _lines(capsys)
    assert lines and all(LINE.match(line) for line in lines), lines


def test_missing_repos_toml_is_a_home_error(estate, capsys):
    (_home() / "governance" / "repos.toml").unlink()
    assert cli.main(["doctor"]) == 1
    assert any(line.startswith("ERROR") and " home:" in line and "not found" in line
               for line in _lines(capsys))


def test_events_check_reports_a_line_number(estate, capsys):
    _, _, log = estate
    log.path.write_text("{not json}\n")
    assert cli.main(["doctor"]) == 1
    err = [line for line in _lines(capsys) if line.startswith("ERROR") and " events:" in line]
    assert err and "1" in err[0] and "json" in err[0].lower(), err


def test_unparsable_policy_is_an_error(estate, capsys):
    (_home() / "governance" / "allocation.toml").write_text("revision = [\n")
    assert cli.main(["doctor"]) == 1
    assert any(line.startswith("ERROR") and " policy:" in line for line in _lines(capsys))


def test_loaded_policy_reports_its_revision(estate, capsys):
    (_home() / "governance" / "allocation.toml").write_text(
        'revision = 41\n[providers.p]\nunit = "tokens"\nwindows = []\n')
    assert cli.main(["doctor"]) == 0
    assert any(line.startswith("OK") and " policy:" in line and "41" in line
               for line in _lines(capsys))


def test_releases_line_reports_how_many_loaded(estate, capsys):
    _, release, _ = estate
    release("aa-fine", ACC)
    release("bb-fine", ACC)
    assert cli.main(["doctor"]) == 0
    ok = [line for line in _lines(capsys) if line.startswith("OK") and " releases:" in line]
    assert ok and "2" in ok[0], ok


def test_landed_release_is_not_drift_warned(estate, capsys):
    repo, release, log = estate
    release("dd-done", ACC)
    for event in (
        make_event("release.published", {"release_id": "dd-done", "revision": 1},
                   item_id="dd-done"),
        make_event("item.landed", {"attempt_id": "dd-done-a1", "train_id": "t1",
                                   "fix_commits": []}, item_id="dd-done"),
    ):
        log.path.parent.mkdir(parents=True, exist_ok=True)
        with open(log.path, "a") as fh:
            fh.write(json.dumps(event) + "\n")
    _commit(repo, "MOVED.txt")
    assert cli.main(["doctor"]) == 0
    assert not any(line.startswith("WARN") and "dd-done" in line for line in _lines(capsys))


def test_doctor_is_read_only(estate, capsys):
    _, release, log = estate
    release("aa-fine", ACC)
    assert cli.main(["doctor"]) == 0
    capsys.readouterr()
    assert log.read() == []
