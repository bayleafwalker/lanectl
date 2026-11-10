"""Extra coverage: every failing test is judged on its own full output."""
import shlex
import subprocess
import sys

from lanectl.gates.failonbase import run_tests_at
from lanectl.lint_release import classify_failure

PY = sys.executable


def test_unknown_shape_is_not_hidden_by_an_expected_failure():
    output = (
        "____________________________ test_a ____________________________\n"
        "E   RuntimeError: mystery\n"
        "____________________________ test_b ____________________________\n"
        "E   AssertionError: nope\n"
    )
    assert classify_failure(output) == "spec-gap"


def test_every_section_must_be_expected():
    expected_only = (
        "____________________________ test_a ____________________________\n"
        "E   ImportError: cannot import name 'Y' from 'm'\n"
        "____________________________ test_b ____________________________\n"
        "E   AssertionError: assert 0 == 3\n"
    )
    assert classify_failure(expected_only) == "expected"
    mixed = (
        "____________________________ test_a ____________________________\n"
        "E   ImportError: cannot import name 'Y' from 'm'\n"
        "____________________________ test_b ____________________________\n"
        "E   RuntimeError: mystery\n"
    )
    assert classify_failure(mixed) == "spec-gap"


def test_argparse_missing_command_or_flag_is_expected():
    assert classify_failure(
        "E       SystemExit: 2\n"
        "lanectl: error: unrecognized arguments: --type item.parked\n"
    ) == "expected"
    assert classify_failure(
        "E       SystemExit: 2\n"
        "lanectl: error: argument cmd: invalid choice: 'thing'\n"
    ) == "expected"


def test_run_tests_at_without_tail_returns_the_full_output(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / "a.txt").write_text("a\n")
    for cmd in (["git", "init", "-q", "-b", "main"], ["git", "add", "-A"],
                ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "b"]):
        subprocess.run(cmd, cwd=repo, check=True, capture_output=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                         capture_output=True, text=True).stdout.strip()
    test_cmd = (f"{shlex.quote(PY)} -c 'print(\"START\" + \"A\" * 5000 + \"END\")' "
                "{files}")
    code, output = run_tests_at(repo, sha, {"t.py": b"x = 1\n"}, test_cmd, tail=None)
    assert code == 0
    assert "START" in output
    assert len(output) > 2000
