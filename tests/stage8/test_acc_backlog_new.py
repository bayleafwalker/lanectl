"""Acceptance: backlog new, publish and rebase (planner-owned)."""
import os
import subprocess
import tomllib
from pathlib import Path

from lanectl import cli
from lanectl.config import load_release

ACC = "def test_ok():\n    assert True\n"
NEW = ["backlog", "new", "aa-new", "--repo", "target", "--title", "Add mul", "--size", "S",
       "--class", "glue", "--scope", "src/**", "--test", "tests/test_acc_mul.py"]


def _home():
    return Path(os.environ["LANECTL_HOME"])


def _head(repo):
    return subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def _commit(repo, name):
    (repo / name).write_text("x\n")
    for cmd in (["add", "-A"], ["commit", "-qm", name]):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *cmd], cwd=repo, check=True)


def test_new_scaffolds_a_loadable_draft_at_main(estate, capsys):
    repo, _, _ = estate
    assert cli.main(NEW) == 0
    d = _home() / "backlog" / "aa-new"
    rel = load_release(d)
    assert rel.draft is True and rel.revision == 1 and rel.base_sha == _head(repo)
    assert rel.repo == "target" and rel.title == "Add mul" and rel.size == "S" and rel.task_class == "glue"
    assert rel.data_class == "public" and rel.scope_paths == ("src/**",)
    assert rel.acceptance.files == ("tests/test_acc_mul.py",)
    assert rel.acceptance.exec and "tests/test_acc_mul.py" in rel.acceptance.exec[0]
    assert (d / "files" / "tests" / "test_acc_mul.py").is_file()
    assert "aa-new" in capsys.readouterr().out


def test_new_refuses_existing_unknown_repo_and_bad_id(estate, capsys):
    assert cli.main(NEW) == 0
    assert cli.main(NEW) == 2
    bad_repo = list(NEW)
    bad_repo[bad_repo.index("target")] = "nope"
    bad_repo[2] = "bb-new"
    assert cli.main(bad_repo) == 2
    bad_id = list(NEW)
    bad_id[2] = "Bad_ID!"
    assert cli.main(bad_id) == 2


def test_publish_refuses_the_unedited_stub(estate, capsys):
    assert cli.main(NEW) == 0
    assert cli.main(["backlog", "publish", "aa-new"]) == 1
    assert load_release(_home() / "backlog" / "aa-new").draft is True


def test_publish_clears_draft_after_edits(estate, capsys):
    assert cli.main(NEW) == 0
    d = _home() / "backlog" / "aa-new"
    (d / "files" / "tests" / "test_acc_mul.py").write_text(
        "from calc import mul\n\n\ndef test_mul():\n    assert mul(2, 3) == 6\n")
    toml = d / "release.toml"
    raw = tomllib.loads(toml.read_text())
    toml.write_text(toml.read_text().replace(raw["outcome"], "Add mul(a, b) to src/calc.py."))
    assert cli.main(["backlog", "publish", "aa-new"]) == 0
    assert load_release(d).draft is False
    assert "outcome" in toml.read_text()


def test_publish_reports_lint_problems(estate, capsys):
    assert cli.main(NEW) == 0
    d = _home() / "backlog" / "aa-new"
    (d / "files" / "tests" / "test_acc_mul.py").write_text(ACC)          # passes on base
    toml = d / "release.toml"
    raw = tomllib.loads(toml.read_text())
    toml.write_text(toml.read_text().replace(raw["outcome"], "Add mul."))
    assert cli.main(["backlog", "publish", "aa-new"]) == 1
    assert "passes-on-base" in capsys.readouterr().out
    assert load_release(d).draft is True


def test_rebase_moves_pending_release_and_bumps_revision(estate, capsys):
    repo, release, _ = estate
    release("cc-old", ACC)
    _commit(repo, "moved.txt")
    assert cli.main(["backlog", "rebase", "cc-old"]) == 0
    rel = load_release(_home() / "backlog" / "cc-old")
    assert rel.base_sha == _head(repo) and rel.revision == 2
    assert cli.main(["backlog", "rebase", "cc-old"]) == 0
    assert load_release(_home() / "backlog" / "cc-old").revision == 2
    assert "up to date" in capsys.readouterr().out


def test_rebase_pending_skips_landed_and_refuses_in_flight(estate, capsys):
    repo, release, log = estate
    for item in ("dd-landed", "ee-flight", "ff-pending"):
        release(item, ACC)
    claim = {"lane": "implement", "model": "scripted/model", "worker": "scripted"}
    log.append("item.claimed", dict(claim, attempt_id="dd-landed-a1"), item_id="dd-landed")
    log.append("item.landed", {"attempt_id": "dd-landed-a1", "train_id": "tt", "fix_commits": []},
               item_id="dd-landed")
    log.append("item.claimed", dict(claim, attempt_id="ee-flight-a1"), item_id="ee-flight")
    base = _head(repo)
    _commit(repo, "moved.txt")
    assert cli.main(["backlog", "rebase", "--pending"]) == 0
    home = _home() / "backlog"
    assert load_release(home / "ff-pending").base_sha == _head(repo)
    assert load_release(home / "dd-landed").base_sha == base
    assert load_release(home / "ee-flight").base_sha == base
    assert cli.main(["backlog", "rebase", "ee-flight"]) == 1
    assert "in flight" in capsys.readouterr().out
