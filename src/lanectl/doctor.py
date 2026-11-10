"""Read-only health checks for a lanectl estate.

Broken releases, stale attempts, drifted bases and missing governance surface
show up today only as failures mid-run (a release that will not load, an
attempt whose runner died, a base that moved under a pending release, a home
that lacks ``governance/repos.toml``).  ``lanectl doctor`` runs every check,
prints one ``{level:5} {check}: {detail}`` line per finding and exits 1 when
any finding is an ERROR, so the estate can be inspected before work is
dispatched.

Every check is read-only: no event is appended and no file is written.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .capacity import AllocationPolicy, parse_ts
from .config import RepoSpec, WorkRelease, home, load_lane, load_release, load_repos
from .events import EventLog, ItemView, project_items
from .runner import git

OK, WARN, ERROR = "OK", "WARN", "ERROR"

#: Timeout used when a claim's lane cannot be loaded (the lane contract default).
DEFAULT_TIMEOUT_S = 2700


@dataclass(frozen=True)
class Finding:
    level: str
    check: str
    detail: str

    def line(self) -> str:
        return f"{self.level:5} {self.check}: {self.detail}"

    def as_dict(self) -> dict:
        return {"level": self.level, "check": self.check, "detail": self.detail}


def _git(repo: Path, *args: str) -> str:
    """Best-effort git query; empty string when git or the repo cannot answer."""
    try:
        return git(repo, *args, check=False)
    except OSError:   # git itself is unavailable
        return ""


def check_home(root: Path) -> list[Finding]:
    """The resolved home and whether the governance entry point is there."""
    repos_toml = root / "governance" / "repos.toml"
    if repos_toml.is_file():
        return [Finding(OK, "home", f"{root} (governance/repos.toml present)")]
    return [Finding(ERROR, "home", f"{root}: governance/repos.toml not found")]


def check_releases(root: Path) -> tuple[list[WorkRelease], list[Finding]]:
    """Load every ``backlog/<dir>/release.toml`` on its own so one bad file shows."""
    releases: list[WorkRelease] = []
    findings: list[Finding] = []
    for path in sorted((root / "backlog").glob("*/release.toml")):
        try:
            releases.append(load_release(path.parent))
        except Exception as exc:   # a broken release must not hide the others
            findings.append(Finding(ERROR, "releases", f"{path.parent.name}: {exc}"))
    loaded, failed = len(releases), len(findings)
    suffix = f", {failed} failed" if failed else ""
    findings.append(Finding(OK, "releases", f"{loaded} release(s) loaded{suffix}"))
    return releases, findings


def _is_checkout(path: Path) -> bool:
    """Whether *path* holds a git checkout (a worktree's ``.git`` may be a file)."""
    if not path.is_dir():
        return False
    if (path / ".git").exists():
        return True
    return bool(_git(path, "rev-parse", "--git-dir"))


def check_repos(root: Path) -> tuple[dict[str, RepoSpec], list[Finding]]:
    """Every repo in ``governance/repos.toml`` has a checkout at its path."""
    try:
        repos = load_repos(root)
    except Exception as exc:
        return {}, [Finding(ERROR, "repos", f"governance/repos.toml: {exc}")]
    findings = [Finding(ERROR, "repos", f"{name}: no git checkout at {spec.path}")
                for name, spec in sorted(repos.items()) if not _is_checkout(spec.path)]
    if not findings:
        findings.append(Finding(OK, "repos", f"{len(repos)} repo(s) at their configured paths"))
    return repos, findings


def check_events(log: EventLog) -> tuple[list[dict] | None, list[Finding]]:
    """The log reads and every line validates against the contract."""
    try:
        events = log.read()
    except Exception as exc:   # unreadable or torn: the rest of the log is unusable
        return None, [Finding(ERROR, "events", str(exc))]
    return events, [Finding(OK, "events", f"{len(events)} event(s)")]


def check_policy(root: Path) -> list[Finding]:
    """The allocation policy is absent (WARN), unparsable (ERROR) or loaded."""
    try:
        policy = AllocationPolicy.load(root=root)
    except Exception as exc:
        return [Finding(ERROR, "policy", str(exc))]
    if policy is None:
        return [Finding(WARN, "policy", "governance/allocation.toml absent: "
                                      "no allocation policy; capacity does not gate admission")]
    return [Finding(OK, "policy", f"allocation revision {policy.revision}")]


def _timeout(claim: dict, cache: dict[str, int]) -> int:
    """The claiming lane's ``timeout_s``, or the contract default if unloadable."""
    name = claim.get("lane") or "implement"
    if name not in cache:
        try:
            cache[name] = load_lane(name).timeout_s
        except Exception:
            cache[name] = DEFAULT_TIMEOUT_S
    return cache[name]


def check_attempts(views: dict[str, ItemView], now: datetime) -> list[Finding]:
    """A claimed item whose open attempt outlived its lane's timeout is stale."""
    now = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    findings: list[Finding] = []
    cache: dict[str, int] = {}
    for item_id, view in sorted(views.items()):
        claim = view.open_attempt
        if claim is None:
            continue
        claimed_at = parse_ts(claim.get("ts"))
        if claimed_at is None:
            continue
        timeout_s = _timeout(claim, cache)
        age_s = (now - claimed_at).total_seconds()
        if age_s <= timeout_s:
            continue
        attempt_id = claim.get("attempt_id", "?")
        findings.append(Finding(
            WARN, "stale-attempts",
            f"{item_id}: attempt {attempt_id} claimed {age_s:.0f}s ago "
            f"(timeout {timeout_s}s); run lanectl reap"))
    return findings


def _main_sha(repo: RepoSpec, cache: dict[str, str]) -> str:
    if repo.name not in cache:
        cache[repo.name] = _git(repo.path, "rev-parse", repo.main)
    return cache[repo.name]


def check_base_drift(releases: list[WorkRelease], repos: dict[str, RepoSpec],
                     views: dict[str, ItemView]) -> list[Finding]:
    """A pending release whose ``base_sha`` is no longer the repo's main commit."""
    findings: list[Finding] = []
    cache: dict[str, str] = {}
    for rel in releases:
        if views.get(rel.id) is not None and views[rel.id].state == "landed":
            continue
        repo = repos.get(rel.repo)
        if repo is None:   # the repos check already reported it
            continue
        current = _main_sha(repo, cache)
        if not current or current == rel.base_sha:
            continue
        findings.append(Finding(
            WARN, "base-drift",
            f"{rel.id}: base_sha {rel.base_sha[:12]} differs from {repo.name} "
            f"{repo.main} {current[:12]}; rebase the release onto main"))
    return findings


def run(log: EventLog, *, root: Path | None = None,
        now: datetime | None = None) -> list[Finding]:
    """Run every check and return the findings in report order."""
    base = root or home()
    now = now or datetime.now(timezone.utc)
    findings = check_home(base)
    releases, release_findings = check_releases(base)
    findings += release_findings
    repos, repo_findings = check_repos(base)
    findings += repo_findings
    events, event_findings = check_events(log)
    findings += event_findings
    findings += check_policy(base)
    if events is not None:
        views = project_items(events)
        findings += check_attempts(views, now)
        findings += check_base_drift(releases, repos, views)
    return findings


def register(sub) -> dict:
    p = sub.add_parser("doctor", help="health checks: home, releases, repos, log, "
                                     "policy, stale attempts, drifted bases")
    p.add_argument("--json", action="store_true", help="emit the findings as JSON")
    return {"doctor": _cmd}


def _cmd(args, log: EventLog) -> int:
    findings = run(log)
    if args.json:
        print(json.dumps([f.as_dict() for f in findings], indent=1))
    else:
        for finding in findings:
            print(finding.line())
    return 1 if any(f.level == ERROR for f in findings) else 0
