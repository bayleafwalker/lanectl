"""Acceptance: `lanectl lint-release` checks a WorkRelease before publishing (planner-owned).

The acceptance tests must fail on base_sha for the *expected* reason: the module
or feature under construction is missing. A failure raised by the test's own
setup (e.g. a ContractError from an invalid fixture id) is a spec gap.
"""
import subprocess
import sys
import textwrap

from lanectl.lint_release import classify_failure, lint_release

PY = sys.executable


def test_classify_failure_kinds():
    assert classify_failure("E   ModuleNotFoundError: No module named 'lanectl.capacity'") == "expected"
    assert classify_failure("E   ImportError: cannot import name 'build_report' from 'lanectl.report'") == "expected"
    assert classify_failure("E   AttributeError: module 'lanectl.cli' has no attribute 'thing'") == "expected"
    assert classify_failure("E   AssertionError: assert 0 == 3") == "expected"
    assert classify_failure("E   lanectl.contracts.ContractError: item_id must match") == "spec-gap"
    assert classify_failure("E   SyntaxError: invalid syntax") == "spec-gap"
    assert classify_failure("E   NameError: name 'helper' is not defined") == "spec-gap"
    assert classify_failure("1 passed in 0.01s") == "passes-on-base"


def _repo(tmp_path):
    repo = tmp_path / "r"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "m.py").write_text("X = 1\n")
    for cmd in (["git", "init", "-q", "-b", "main"], ["git", "add", "-A"],
                ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "b"]):
        subprocess.run(cmd, cwd=repo, check=True, capture_output=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    return repo, sha


def _release(tmp_path, repo_name, sha, test_body):
    d = tmp_path / "home" / "backlog" / "it-1"
    (d / "files" / "tests").mkdir(parents=True, exist_ok=True)
    (d / "files" / "tests" / "test_acc_it.py").write_text(test_body)
    (d / "release.toml").write_text(textwrap.dedent(f"""
        id = "it-1"
        repo = "{repo_name}"
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


def test_lint_release_end_to_end(tmp_path, monkeypatch):
    repo, sha = _repo(tmp_path)
    home = tmp_path / "home"
    (home / "governance" / "lanes").mkdir(parents=True)
    (home / "governance" / "repos.toml").write_text(textwrap.dedent(f"""
        [repos.r]
        path = "{repo}"
        test_cmd = "PYTHONPATH=src {PY} -m pytest -q -p no:cacheprovider {{files}}"
        check_cmd = "true"
        worktree_root = "{tmp_path / 'wt'}"
        """))
    monkeypatch.setenv("LANECTL_HOME", str(home))

    good = _release(tmp_path, "r", sha, "from m import Y\n\ndef test_y():\n    assert Y == 2\n")
    assert lint_release(good) == []

    vacuous = _release(tmp_path, "r", sha, "from m import X\n\ndef test_x():\n    assert X == 1\n")
    assert [p.split(":")[0] for p in lint_release(vacuous)] == ["passes-on-base"]

    broken = _release(tmp_path, "r", sha, "def test_x():\n    assert helper() == 1\n")
    assert [p.split(":")[0] for p in lint_release(broken)] == ["spec-gap"]
