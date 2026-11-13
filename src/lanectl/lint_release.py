"""Pre-flight check: acceptance tests must fail on base_sha for the right reason.

A planner-owned acceptance test that passes on base does not test the change. A
test that fails because its own fixtures are invalid (for example a
ContractError from a bad id) is a spec gap, not evidence that the feature is
missing. Running the acceptance files on the release's base commit and
classifying the failure catches both before an attempt is spent.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .config import load_lane, load_release, load_repos, match
from .contracts import ContractError
from .gates.failonbase import run_tests_at

# Used when a release names no lane or its lane revision is unavailable (for
# example a release checked outside a full LANECTL_HOME). Mirrors the defaults
# in governance/lanes/implement.toml.
DEFAULT_TEST_GLOBS = ("tests/**/test_*.py", "**/tests/**/test_*.py",
                      "**/*.test.ts", "**/*_test.go")

# Failures that indicate the feature under construction is missing: the test
# imports it, calls it, or asserts on behaviour that does not exist yet.
_EXPECTED = (
    re.compile(r"\bModuleNotFoundError\b"),
    re.compile(r"\bImportError\b"),
    re.compile(r"\bAttributeError\b"),
    re.compile(r"\bAssertionError\b"),
    # argparse rejects a command or flag that the CLI does not implement yet.
    re.compile(r"\bunrecognized arguments\b"),
    re.compile(r"\binvalid choice\b"),
    # A quoted key the product data does not carry yet (a row or mapping field
    # the feature is supposed to add); a bare KeyError stays unknown.
    re.compile(r"""\bKeyError:\s*(?:'[^']*'|"[^"]*")"""),
)

# pytest.raises that did not raise: the code that should raise is absent, and
# that holds for any exception the test names, including ContractError. It is
# checked before _SPEC_GAP so the named class does not decide the kind.
_DID_NOT_RAISE = re.compile(r"\bDID NOT RAISE\b")

# A ContractError the test or its fixtures actually raised, rather than one a
# test merely expected: a traceback line (``ContractError: ...``) or pytest's
# ``E   lanectl.contracts.ContractError`` line.
_CONTRACT_RAISED = re.compile(
    r"(?:\bE\s+(?:lanectl\.contracts\.)?ContractError\b"
    r"|(?:^|\n)[ \t]*(?:lanectl\.contracts\.)?ContractError:)"
)

# Failures raised by the test itself rather than by missing product code.
_MISSING_TEST_MODULE = re.compile(
    r"\bModuleNotFoundError:\s*No module named [\"']tests(?:\.[^\"']+)?[\"']"
)

_MISSING_TEST_SYMBOL = re.compile(
    r"\bImportError:\s*cannot import name [\"'][^\"']+[\"']\s+from "
    r"[\"']tests(?:\.[A-Za-z_][A-Za-z0-9_]*)*[\"']"
)

_SPEC_GAP = (
    _CONTRACT_RAISED,
    re.compile(r"\bSyntaxError\b"),
    re.compile(r"\bNameError\b"),
)

_PASSED = re.compile(r"\b\d+ passed\b")
_FAILED = re.compile(r"\b\d+ (?:failed|errors?)\b")

# pytest separates the traceback for each failing test with an underscored
# heading naming that test. Splitting on it keeps one test's errors from
# deciding the classification of every other test in the run.
_SECTION_HEADING = re.compile(r"^_{5,}\s+.+?\s+_{5,}$")


def _passed(output: str) -> bool:
    return bool(_PASSED.search(output)) and not _FAILED.search(output)


def _sections(output: str) -> list[str]:
    """Split pytest output into per-test failure/error sections."""
    sections: list[str] = []
    current: list[str] | None = None
    for line in output.splitlines():
        if _SECTION_HEADING.match(line):
            if current is not None:
                sections.append("\n".join(current))
            current = [line]
        elif current is not None:
            current.append(line)
    if current is not None:
        sections.append("\n".join(current))
    return sections


def _classify_one(output: str) -> str:
    if _MISSING_TEST_MODULE.search(output) or _MISSING_TEST_SYMBOL.search(output):
        return "spec-gap"
    if _DID_NOT_RAISE.search(output):
        return "expected"
    if any(p.search(output) for p in _SPEC_GAP):
        return "spec-gap"
    if any(p.search(output) for p in _EXPECTED):
        return "expected"
    # Unknown failure shapes are treated conservatively: something in the test
    # or its fixtures is not understood yet, so a planner should look at it.
    return "spec-gap"


def classify_failure(output: str) -> str:
    """Classify a pytest run's output as expected failure, spec gap, or vacuous."""
    output = output or ""
    if _passed(output):
        return "passes-on-base"
    sections = _sections(output) or [output]
    if all(_classify_one(section) == "expected" for section in sections):
        return "expected"
    return "spec-gap"


def _test_globs(release) -> tuple[str, ...]:
    for name in release.eligible_lanes:
        try:
            lane = load_lane(name)
        except (OSError, ContractError):
            continue
        return lane.test_globs
    return DEFAULT_TEST_GLOBS


def _summary(output: str) -> str:
    """Last non-empty line, which is normally pytest's failure summary."""
    lines = [ln.strip() for ln in (output or "").splitlines() if ln.strip()]
    return lines[-1][:300] if lines else "no output"


def _acceptance_files(release, release_dir: Path) -> tuple[dict[str, bytes], list[str]]:
    files: dict[str, bytes] = {}
    problems: list[str] = []
    for name in release.acceptance.files:
        path = release_dir / "files" / name
        if not path.is_file():
            problems.append(f"spec-gap: {name} :: acceptance file is missing from the release")
            continue
        files[name] = path.read_bytes()
    return files, problems


def lint_release(release_dir) -> list[str]:
    """Return problems that would make this release fail on base for the wrong reason."""
    release_dir = Path(release_dir)
    try:
        release = load_release(release_dir)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f"spec-gap: {release_dir} :: cannot load release: {exc}"]

    try:
        repo = load_repos()[release.repo]
    except (OSError, KeyError) as exc:
        return [f"spec-gap: {release_dir} :: cannot load repo {release.repo!r}: {exc}"]

    files, problems = _acceptance_files(release, release_dir)
    if not files:
        return problems

    # One run per file keeps a mixed result attributable to the file that
    # caused it; classify_failure works on a single outcome.
    globs = _test_globs(release)
    for name in files:
        if not match(name, globs):
            continue
        try:
            code, output = run_tests_at(repo.path, release.base_sha, files,
                                        repo.test_cmd, repo.setup_cmd, tail=None,
                                        selected_files=[name])
        except (OSError, subprocess.SubprocessError) as exc:
            problems.append(f"spec-gap: {name} :: base run failed: {exc}")
            continue
        kind = "passes-on-base" if code == 0 else classify_failure(output)
        if kind != "expected":
            problems.append(f"{kind}: {name} :: {_summary(output)}")
    return problems


def register(sub) -> dict:
    p = sub.add_parser(
        "lint-release",
        help="check that acceptance tests fail on base_sha for the expected reason",
    )
    p.add_argument("release_dirs", nargs="+", metavar="release-dir")
    return {"lint-release": _cmd}


def _cmd(args, log) -> int:
    failed = False
    for release_dir in args.release_dirs:
        problems = lint_release(release_dir)
        if problems:
            failed = True
            for problem in problems:
                print(f"{release_dir}: {problem}")
        else:
            print(f"{release_dir}: OK")
    return 1 if failed else 0
