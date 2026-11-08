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
                 setup_cmd: str = "", timeout: int = 900) -> tuple[int, str]:
    """Check out `rev` in a throwaway worktree, drop in `test_files`, run them."""
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
        cmd = test_cmd.replace("{files}", " ".join(shlex.quote(f) for f in test_files))
        p = subprocess.run(cmd, shell=True, cwd=wt, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr)[-2000:]
    finally:
        subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", str(wt)],
                       capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)


def check(repo: Path, base: str, test_files: dict[str, bytes], test_cmd: str,
          setup_cmd: str = "") -> list[str]:
    if not test_files:
        return []
    code, tail = run_tests_at(repo, base, test_files, test_cmd, setup_cmd)
    if code == 0:
        return [f"passes-on-base: {sorted(test_files)}"]
    if code == 5:  # pytest: no tests collected
        return [f"no-tests-collected-on-base: {sorted(test_files)}"]
    return []
