"""Acceptance: lanectl doctor (planner-owned)."""
import json
import os
import subprocess
from pathlib import Path

from lanectl import cli
from lanectl.contracts import make_event

ACC = "def test_ok():\n    assert True\n"


def _lines(capsys):
    return capsys.readouterr().out.splitlines()


def _home():
    return Path(os.environ["LANECTL_HOME"])


def test_healthy_estate_exits_0_with_ok_lines(estate, capsys):
    _, release, _ = estate
    release("aa-fine", ACC)
    assert cli.main(["doctor"]) == 0
    lines = _lines(capsys)
    assert not any(line.startswith("ERROR") for line in lines)
    for check in ("home", "releases", "repos", "events"):
        assert any(line.startswith("OK") and f" {check}:" in line for line in lines), (check, lines)


def test_broken_release_is_an_error_naming_it(estate, capsys):
    _, release, _ = estate
    release("aa-fine", ACC)
    release("bb-broken", ACC)
    toml = _home() / "backlog" / "bb-broken" / "release.toml"
    toml.write_text(toml.read_text().replace('size = "S"', 'size = "XL"'))
    assert cli.main(["doctor"]) == 1
    lines = _lines(capsys)
    assert any(line.startswith("ERROR") and "bb-broken" in line for line in lines), lines
    assert not any(line.startswith("ERROR") and "aa-fine" in line for line in lines)


def test_missing_repo_path_is_an_error(estate, capsys):
    repo, _, _ = estate
    repos = _home() / "governance" / "repos.toml"
    repos.write_text(repos.read_text().replace(str(repo), str(repo) + "-gone"))
    assert cli.main(["doctor"]) == 1
    assert any(line.startswith("ERROR") and "target" in line for line in _lines(capsys))


def test_stale_open_attempt_warns_to_reap(estate, capsys):
    _, release, log = estate
    release("cc-stuck", ACC)
    ev = make_event("item.claimed", {"attempt_id": "cc-stuck-a1", "lane": "implement",
                                     "model": "scripted/model", "worker": "scripted"},
                    item_id="cc-stuck", ts="2026-01-01T00:00:00Z")
    log.path.parent.mkdir(parents=True, exist_ok=True)
    with open(log.path, "a") as fh:
        fh.write(json.dumps(ev) + "\n")
    assert cli.main(["doctor"]) == 0
    warn = [line for line in _lines(capsys) if line.startswith("WARN") and "cc-stuck-a1" in line]
    assert warn and "reap" in warn[0]


def test_release_behind_main_warns(estate, capsys):
    repo, release, _ = estate
    release("dd-behind", ACC)
    (repo / "NEW.txt").write_text("x\n")
    for cmd in (["add", "-A"], ["commit", "-qm", "moved"]):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *cmd], cwd=repo, check=True)
    assert cli.main(["doctor"]) == 0
    warn = [line for line in _lines(capsys) if line.startswith("WARN") and "dd-behind" in line]
    assert warn and "base_sha" in warn[0]


def test_missing_policy_is_a_warning(estate, capsys):
    assert cli.main(["doctor"]) == 0
    assert any(line.startswith("WARN") and "policy" in line for line in _lines(capsys))


def test_json_output(estate, capsys):
    _, release, _ = estate
    release("aa-fine", ACC)
    assert cli.main(["doctor", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows and all(set(r) == {"level", "check", "detail"} for r in rows)
    assert {r["level"] for r in rows} <= {"OK", "WARN", "ERROR"}
