"""Extra coverage for the release linter: classification, missing files, CLI."""
import subprocess
import sys
import textwrap

from lanectl import cli
from lanectl import lint_release as lint_release_module
from lanectl.lint_release import classify_failure, lint_release

PY = sys.executable


def test_classify_failure_prefers_spec_gap_and_flags_unknown():
    both = "E   ImportError: no module\nE   lanectl.contracts.ContractError: bad id\n"
    assert classify_failure(both) == "spec-gap"
    assert classify_failure("2 failed, 1 passed in 0.1s") == "spec-gap"
    assert classify_failure("E   RuntimeError: mystery") == "spec-gap"


def _repo(tmp_path):
    repo = tmp_path / "r"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "m.py").write_text("X = 1\n")
    for cmd in (["git", "init", "-q", "-b", "main"], ["git", "add", "-A"],
                ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "b"]):
        subprocess.run(cmd, cwd=repo, check=True, capture_output=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                         capture_output=True, text=True).stdout.strip()
    return repo, sha


def _release(tmp_path, name, sha, test_body):
    d = tmp_path / "home" / "backlog" / name
    (d / "files" / "tests").mkdir(parents=True, exist_ok=True)
    (d / "files" / "tests" / "test_acc_it.py").write_text(test_body)
    (d / "release.toml").write_text(textwrap.dedent(f"""
        id = "{name}"
        repo = "r"
        base_sha = "{sha}"
        title = "t"
        outcome = "o"
        task_class = "glue"
        size = "S"
        data_class = "public"
        [scope]
        paths = ["src/**", "tests/**"]
        [acceptance]
        exec = ["true"]
        files = ["tests/test_acc_it.py"]
        """))
    return d


def _home(tmp_path, repo):
    home = tmp_path / "home"
    (home / "governance" / "lanes").mkdir(parents=True)
    (home / "governance" / "repos.toml").write_text(textwrap.dedent(f"""
        [repos.r]
        path = "{repo}"
        test_cmd = "PYTHONPATH=src {PY} -m pytest -q -p no:cacheprovider {{files}}"
        check_cmd = "true"
        worktree_root = "{tmp_path / 'wt'}"
        """))
    return home


def test_lint_release_reports_missing_acceptance_file(tmp_path, monkeypatch):
    repo, sha = _repo(tmp_path)
    monkeypatch.setenv("LANECTL_HOME", str(_home(tmp_path, repo)))
    d = _release(tmp_path, "missing", sha, "def test_x():\n    assert True\n")
    (d / "files" / "tests" / "test_acc_it.py").unlink()
    problems = lint_release(d)
    assert [p.split(":")[0] for p in problems] == ["spec-gap"]
    assert "missing" in problems[0]


def test_lint_release_reports_base_run_failure(tmp_path, monkeypatch):
    repo, sha = _repo(tmp_path)
    monkeypatch.setenv("LANECTL_HOME", str(_home(tmp_path, repo)))
    d = _release(tmp_path, "boom", sha, "from m import Y\n\ndef test_y():\n    assert Y == 2\n")

    def boom(*args, **kwargs):
        raise OSError("cannot create worktree")

    monkeypatch.setattr(lint_release_module, "run_tests_at", boom)
    problems = lint_release(d)
    assert [p.split(":")[0] for p in problems] == ["spec-gap"]
    assert "cannot create worktree" in problems[0]


def test_cli_lint_release_exit_codes(tmp_path, monkeypatch, capsys):
    repo, sha = _repo(tmp_path)
    monkeypatch.setenv("LANECTL_HOME", str(_home(tmp_path, repo)))
    monkeypatch.setenv("LANECTL_STATE", str(tmp_path / "state"))
    good = _release(tmp_path, "good", sha, "from m import Y\n\ndef test_y():\n    assert Y == 2\n")
    vacuous = _release(tmp_path, "vacuous", sha,
                       "from m import X\n\ndef test_x():\n    assert X == 1\n")

    assert cli.main(["lint-release", str(good)]) == 0
    assert "OK" in capsys.readouterr().out

    assert cli.main(["lint-release", str(good), str(vacuous)]) == 1
    out = capsys.readouterr().out
    assert "passes-on-base" in out
    assert "OK" in out
