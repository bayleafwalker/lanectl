"""New tests must fail on the base commit; otherwise they do not test the change.

Governance path.
"""
from __future__ import annotations

import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path


def run_tests_at(repo: Path, rev: str, test_files: dict[str, bytes], test_cmd: str,
                 setup_cmd: str = "", timeout: int = 900, wrap=None,
                 tail: int | None = 2000, *,
                 selected_files: list[str] | None = None) -> tuple[int, str]:
    """Check out `rev` in a throwaway worktree, drop in `test_files`, run them.

    All `test_files` are materialized; `selected_files` limits execution to
    declared paths. By default all materialized files are executed.

    `tail` keeps the last N characters of output; pass None for the full output
    when a caller needs to inspect every failure rather than the final one.
    """
    if selected_files is not None and (not selected_files or
                                       any(name not in test_files for name in selected_files)):
        raise ValueError("selected files must be a non-empty subset of test_files")
    execution_files = test_files if selected_files is None else selected_files
    tmp = Path(tempfile.mkdtemp(prefix="lanectl-base-"))
    wt = tmp / "wt"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "--detach", str(wt), rev],
                   check=True, capture_output=True)
    try:
        for rel, data in test_files.items():
            dst = wt / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
        if setup_cmd:
            subprocess.run(setup_cmd, shell=True, cwd=wt, capture_output=True, timeout=timeout)
        cmd = test_cmd.replace("{files}", " ".join(shlex.quote(f) for f in execution_files))
        if wrap:   # worker-written tests are untrusted code: run them sandboxed
            cmd = wrap(cmd, wt)
        p = subprocess.run(cmd, shell=True, cwd=wt, capture_output=True, text=True, timeout=timeout)
        output = p.stdout + p.stderr
        return p.returncode, output if tail is None else output[-tail:]
    finally:
        subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", str(wt)],
                       capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)


def check(repo: Path, base: str, test_files: dict[str, bytes], test_cmd: str,
          setup_cmd: str = "", wrap=None) -> list[str]:
    if not test_files:
        return []
    code, tail = run_tests_at(repo, base, test_files, test_cmd, setup_cmd, wrap=wrap)
    if code == 0:
        return [f"passes-on-base: {sorted(test_files)}"]
    if code == 5:  # pytest: no tests collected
        return [f"no-tests-collected-on-base: {sorted(test_files)}"]
    return []
