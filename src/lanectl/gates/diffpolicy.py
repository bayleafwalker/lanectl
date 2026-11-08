"""Diff-policy gate: scope, protected paths, size, dependencies, test integrity.

Governance path. Cheapest gate; runs before anything executes worker code.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..config import match
from ..contracts import LaneRevision, WorkRelease


@dataclass
class FileChange:
    status: str          # A, M, D, R (rename collapses to D old + A new)
    path: str
    added: int = 0
    deleted: int = 0
    added_lines: list[str] = field(default_factory=list)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout


def collect(repo: Path, base: str, head: str) -> list[FileChange]:
    changes: dict[str, FileChange] = {}
    for line in _git(repo, "diff", "--no-renames", "--name-status", base, head).splitlines():
        status, path = line.split("\t", 1)
        changes[path] = FileChange(status[0], path)
    for line in _git(repo, "diff", "--no-renames", "--numstat", base, head).splitlines():
        a, d, path = line.split("\t", 2)
        if path in changes:
            changes[path].added = int(a) if a != "-" else 0
            changes[path].deleted = int(d) if d != "-" else 0
    cur = None
    for line in _git(repo, "diff", "--no-renames", "-U0", base, head).splitlines():
        if line.startswith("+++ "):
            cur = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("+") and not line.startswith("+++") and cur in changes:
            changes[cur].added_lines.append(line[1:])
    return list(changes.values())


def evaluate(changes: list[FileChange], rel: WorkRelease, lane: LaneRevision,
             acceptance_paths: tuple[str, ...] = ()) -> list[str]:
    """Pure policy. Returns violations; each starts with a stable rule id."""
    v: list[str] = []
    total = 0
    for c in changes:
        total += c.added + c.deleted
        if match(c.path, acceptance_paths):
            v.append(f"protected-path: {c.path}")
            continue
        if match(c.path, lane.protected_paths):
            # Governance paths are writable only when the release scopes them
            # explicitly; such changes always go to interactive review.
            v.append(f"{'protected-review' if match(c.path, rel.scope_paths) else 'protected-path'}: {c.path}")
            continue
        if not match(c.path, rel.scope_paths):
            v.append(f"out-of-scope: {c.path}")
        if not rel.allow_deps and match(c.path, lane.dependency_manifests):
            v.append(f"dependency-change: {c.path}")
        is_test = match(c.path, lane.test_globs)
        if is_test and c.status in ("M", "D") and not rel.allow_test_edits:
            if c.status == "D" or c.deleted:
                v.append(f"existing-test-modified: {c.path}")
        for line in c.added_lines:
            for pat in lane.forbidden_added_patterns:
                if re.search(pat, line):
                    v.append(f"forbidden-pattern: {c.path}: /{pat}/")
                    break
    budget = lane.size_budget_lines.get(rel.size)
    if budget is not None and total > budget:
        v.append(f"size-budget: {total} changed lines > {budget} for size {rel.size}")
    return v


def review_only(violations: list[str]) -> bool:
    return bool(violations) and all(x.startswith("protected-review:") for x in violations)


def is_protected_violation(violations: list[str]) -> bool:
    return any(x.startswith("protected-path:") for x in violations)
