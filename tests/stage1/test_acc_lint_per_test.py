"""Acceptance: lint-release judges every failing test, not the output tail (planner-owned)."""
import subprocess
import sys
import textwrap

from lanectl.lint_release import classify_failure, lint_release

PY = sys.executable
LONG = "raise AssertionError('x' * 5000)"


def test_argparse_missing_feature_is_expected():
    out = ("E       SystemExit: 2\n"
           "lanectl: error: unrecognized arguments: --type item.parked\n")
    assert classify_failure(out) == "expected"
    out = "E       SystemExit: 2\nlanectl: error: argument cmd: invalid choice: 'thing'\n"
    assert classify_failure(out) == "expected"


def _home(tmp_path, monkeypatch, test_body):
    repo = tmp_path / "r"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "m.py").write_text("X = 1\n")
    for cmd in (["git", "init", "-q", "-b", "main"], ["git", "add", "-A"],
                ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "b"]):
        subprocess.run(cmd, cwd=repo, check=True, capture_output=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
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
    d = home / "backlog" / "it-1"
    (d / "files" / "tests").mkdir(parents=True)
    (d / "files" / "tests" / "test_acc_it.py").write_text(test_body)
    (d / "release.toml").write_text(textwrap.dedent(f"""
        id = "it-1"
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


def test_early_spec_gap_is_not_hidden_by_a_long_last_failure(tmp_path, monkeypatch):
    # 40 later expected failures push the early NameError out of any output tail.
    body = ("import pytest\n\ndef test_a():\n    assert helper() == 1\n\n"
            f"@pytest.mark.parametrize('i', range(40))\ndef test_b(i):\n    {LONG}\n")
    d = _home(tmp_path, monkeypatch, body)
    assert [p.split(":")[0] for p in lint_release(d)] == ["spec-gap"]


def test_all_expected_failures_pass_lint_despite_long_output(tmp_path, monkeypatch):
    body = f"from m import Y\n\ndef test_a():\n    assert Y\n\ndef test_b():\n    {LONG}\n"
    d = _home(tmp_path, monkeypatch, body)
    assert lint_release(d) == []
