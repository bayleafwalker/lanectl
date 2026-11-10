"""Extra coverage: backlog new defaults, publish guards and rebase text edits."""
import os
import subprocess
from pathlib import Path

from lanectl import cli
from lanectl.config import load_release

ACC = "def test_ok():\n    assert True\n"
NEW = ["backlog", "new", "gg-new", "--repo", "target", "--title", "Add mul",
       "--scope", "src/**", "--scope", "tests/**"]
CLAIM = {"lane": "implement", "model": "scripted/model", "worker": "scripted"}


def _home():
    return Path(os.environ["LANECTL_HOME"])


def _head(repo):
    return subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


def _commit(repo, name):
    (repo / name).write_text("x\n")
    for cmd in (["add", "-A"], ["commit", "-qm", name]):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *cmd],
                       cwd=repo, check=True)


def test_new_defaults_size_class_data_and_derived_test(estate, capsys):
    assert cli.main(NEW) == 0
    d = _home() / "backlog" / "gg-new"
    rel = load_release(d)
    assert rel.size == "S" and rel.task_class == "glue" and rel.data_class == "public"
    assert rel.acceptance.files == ("tests/test_acc_gg_new.py",)
    assert rel.scope_paths == ("src/**", "tests/**")
    assert rel.draft is True and rel.revision == 1 and rel.base_sha == _head(estate[0])
    assert "write the acceptance test" in (d / "files" / "tests" / "test_acc_gg_new.py").read_text()
    assert "gg-new" in capsys.readouterr().out


def test_new_honours_data_class_and_class_flags(estate):
    argv = ["backlog", "new", "hh-new", "--repo", "target", "--title", "T", "--scope", "src/**",
            "--class", "view", "--size", "M", "--data-class", "restricted",
            "--test", "tests/test_acc_custom.py"]
    assert cli.main(argv) == 0
    rel = load_release(_home() / "backlog" / "hh-new")
    assert rel.task_class == "view" and rel.size == "M" and rel.data_class == "restricted"
    assert rel.acceptance.files == ("tests/test_acc_custom.py",)
    assert "tests/test_acc_custom.py" in rel.acceptance.exec[0]


def test_new_bad_id_writes_nothing(estate, capsys):
    argv = list(NEW)
    argv[2] = "Bad_ID!"
    assert cli.main(argv) == 2
    assert not (_home() / "backlog" / "Bad_ID!").exists()
    assert "Bad_ID!" in capsys.readouterr().err


def test_publish_says_already_published(estate, capsys):
    _, release, _ = estate
    release("ii-done", ACC)
    assert cli.main(["backlog", "publish", "ii-done"]) == 0
    assert "already published" in capsys.readouterr().out


def test_publish_refuses_todo_outcome_even_with_a_real_test(estate, capsys):
    assert cli.main(NEW) == 0
    d = _home() / "backlog" / "gg-new"
    (d / "files" / "tests" / "test_acc_gg_new.py").write_text(ACC)
    assert cli.main(["backlog", "publish", "gg-new"]) == 1
    assert "TODO" in capsys.readouterr().out
    assert load_release(d).draft is True


def test_rebase_adds_a_missing_revision_line(estate, capsys):
    repo, release, _ = estate
    release("jj-old", ACC)
    base = _head(repo)
    _commit(repo, "moved.txt")
    assert cli.main(["backlog", "rebase", "jj-old"]) == 0
    assert f"jj-old: {base[:12]} -> {_head(repo)[:12]} r2" in capsys.readouterr().out
    toml = (_home() / "backlog" / "jj-old" / "release.toml").read_text()
    assert "revision = 2" in toml
    rel = load_release(_home() / "backlog" / "jj-old")
    assert rel.revision == 2 and rel.base_sha == _head(repo)


def test_rebase_pending_leaves_in_flight_alone(estate):
    repo, release, log = estate
    release("kk-flight", ACC)
    release("ll-pending", ACC)
    log.append("item.claimed", dict(CLAIM, attempt_id="kk-flight-a1"), item_id="kk-flight")
    base = _head(repo)
    _commit(repo, "moved.txt")
    assert cli.main(["backlog", "rebase", "--pending"]) == 0
    home = _home() / "backlog"
    assert load_release(home / "kk-flight").base_sha == base
    assert load_release(home / "ll-pending").base_sha == _head(repo)
    assert load_release(home / "ll-pending").revision == 2


def test_rebase_unknown_id_exits_2(estate, capsys):
    assert cli.main(["backlog", "rebase", "zz-missing"]) == 2
    assert "unknown release" in capsys.readouterr().err
