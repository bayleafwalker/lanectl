"""Repo-declared gate jobs, each one its own gate after acceptance passes.

A gate job is an extra check a repo declares in ``governance/repos.toml``
(``[[repos.<r>.gate_jobs]]``).  It runs in the attempt worktree, in the same
sandbox as the acceptance commands, and only once acceptance is green: an
attempt that fails a job is never gate-accepted, so evaluator evidence only
sees work that passed every job.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .config import GateJob


def run_jobs(jobs: tuple[GateJob, ...], worktree: Path, wrap=None) -> dict[str, list[str]]:
    """Run ``jobs`` in order; one ``job:<name>`` entry per job.

    ``wrap(cmd, worktree)`` is the attempt sandbox, exactly as for acceptance
    commands.  An empty list means the job passed; a non-zero exit or a timeout
    is a violation carrying the job's tail so ``decide()`` rejects like any gate.
    """
    out: dict[str, list[str]] = {}
    for job in jobs:
        cmd = wrap(job.cmd, worktree) if wrap else job.cmd
        try:
            p = subprocess.run(cmd, shell=True, cwd=worktree, capture_output=True,
                               text=True, timeout=job.timeout_s)
        except subprocess.TimeoutExpired:
            out[f"job:{job.name}"] = [f"timeout after {job.timeout_s}s: {job.name}"]
            continue
        if p.returncode:
            out[f"job:{job.name}"] = [
                f"exit {p.returncode}: {job.name} :: {(p.stdout + p.stderr)[-600:]}"]
        else:
            out[f"job:{job.name}"] = []
    return out
