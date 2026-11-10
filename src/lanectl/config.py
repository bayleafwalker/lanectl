"""Load governance (lanes, repos) and backlog (WorkReleases) from LANECTL_HOME.

LANECTL_HOME is a checkout of this repository's main branch. Lanes write only to
lane/* branches in worktrees, so the governance they are judged by is never in
their write scope. When LANECTL_HOME is unset the checkout is found by walking up
from the working directory, so an installed lanectl works inside a checkout.
"""
from __future__ import annotations

import hashlib
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .contracts import DATA_CLASSES, Acceptance, ContractError, LaneRevision, WorkRelease


def _checkout_above(start: Path) -> Path | None:
    """Nearest directory at or above ``start`` that holds a governance checkout."""
    for candidate in (start, *start.parents):
        if (candidate / "governance" / "repos.toml").is_file():
            return candidate
    return None


def home() -> Path:
    h = os.environ.get("LANECTL_HOME")
    if h:
        return Path(h)
    found = _checkout_above(Path.cwd())
    if found is not None:
        return found
    return Path(__file__).resolve().parents[2]


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def match(path: str, globs) -> bool:
    p = PurePosixPath(path)
    return any(p.full_match(g) for g in globs)


@dataclass(frozen=True)
class GateJob:
    """One extra check run in the attempt worktree after acceptance passes."""
    name: str
    cmd: str
    timeout_s: int = 600


@dataclass(frozen=True)
class DeploySpec:
    """How a repo's train is deployed to a throwaway dev namespace and torn down."""
    cmd: str
    health_cmd: str
    teardown_cmd: str
    ttl_s: int = 3600
    env_allow: tuple[str, ...] = ()     # inherited variables; everything else is stripped


@dataclass(frozen=True)
class RepoSpec:
    name: str
    path: Path
    main: str
    test_cmd: str           # fail-on-base runner; {files} is replaced with test paths
    check_cmd: str          # whole-repo check for trains
    worktree_root: Path
    setup_cmd: str = ""     # run once in a fresh worktree before anything else
    protected_paths: tuple[str, ...] = ()   # extra protected globs for this repo
    data_class_floor: str = "public"        # "restricted" treats every release as restricted
    routing: dict[str, float] = field(default_factory=dict)  # overrides lane weights when set
    gate_jobs: tuple[GateJob, ...] = ()     # in the order repos.toml lists them
    deploy: DeploySpec | None = None        # None means the repo has no dev deploy
    # "local": `land` is the landing. "pr": main reaches the forge through a reviewed PR, so a
    # tracker item closes only once the landed commit is on origin/<main> (operator, 2026-11-10).
    landing: str = "local"


_GATE_JOB_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")     # gate names are also event keys


def _landing(repo: str, value) -> str:
    if value not in ("local", "pr"):
        raise ContractError(f"{repo}: landing must be \"local\" or \"pr\"")
    return value


def _positive_int(repo: str, where: str, key: str, value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractError(f"{repo}: {where} {key} must be a positive integer")
    return value


def _required_str(repo: str, where: str, key: str, raw: dict) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{repo}: {where} missing {key}")
    return value


def _gate_jobs(repo: str, tables) -> tuple[GateJob, ...]:
    jobs, seen = [], set()
    for index, raw in enumerate(tables):
        where = f"gate_jobs[{index}]"
        if not isinstance(raw, dict):
            raise ContractError(f"{repo}: {where} must be a table")
        name = _required_str(repo, where, "name", raw)
        if not _GATE_JOB_NAME.fullmatch(name):
            raise ContractError(
                f"{repo}: {where} name {name!r} must be lowercase letters, digits and hyphens, "
                "starting with a letter or digit")
        if name in seen:
            raise ContractError(f"{repo}: duplicate gate job {name!r}")
        seen.add(name)
        jobs.append(GateJob(name=name, cmd=_required_str(repo, where, "cmd", raw),
                            timeout_s=_positive_int(repo, where, "timeout_s",
                                                    raw.get("timeout_s", 600))))
    return tuple(jobs)


def _deploy(repo: str, raw) -> DeploySpec:
    if not isinstance(raw, dict):
        raise ContractError(f"{repo}: deploy must be a table")
    env_allow = raw.get("env_allow", [])
    if not isinstance(env_allow, list) or any(not isinstance(v, str) for v in env_allow):
        raise ContractError(f"{repo}: deploy env_allow must be a list of strings")
    for entry in env_allow:
        if entry.startswith("LANE_"):
            raise ContractError(
                f"{repo}: deploy env_allow {entry!r} is reserved for lanectl (LANE_ prefix)")
    return DeploySpec(
        cmd=_required_str(repo, "deploy", "cmd", raw),
        health_cmd=_required_str(repo, "deploy", "health_cmd", raw),
        teardown_cmd=_required_str(repo, "deploy", "teardown_cmd", raw),
        ttl_s=_positive_int(repo, "deploy", "ttl_s", raw.get("ttl_s", 3600)),
        env_allow=tuple(env_allow),
    )


def load_lane(name: str, root: Path | None = None) -> LaneRevision:
    path = (root or home()) / "governance" / "lanes" / f"{name}.toml"
    raw = tomllib.loads(path.read_text())
    try:
        return LaneRevision(
            lane=raw["lane"], revision=int(raw["revision"]),
            size_max=raw["eligibility"]["size_max"],
            routing={k: float(v) for k, v in raw["routing"]["weights"].items()},
            max_attempts=int(raw["routing"]["max_attempts"]),
            retry=raw["routing"]["retry"],
            caps={k: int(v) for k, v in raw["caps"].items()},
            size_budget_lines={k: int(v) for k, v in raw["gates"]["size_budget_lines"].items()},
            protected_paths=tuple(raw["gates"]["protected_paths"]),
            dependency_manifests=tuple(raw["gates"]["dependency_manifests"]),
            test_globs=tuple(raw["gates"]["test_globs"]),
            forbidden_added_patterns=tuple(raw["gates"]["forbidden_added_patterns"]),
            external_models=tuple(raw["routing"].get("external_models", ())),
            timeout_s=int(raw["routing"].get("timeout_s", 2700)),
            effects=dict(raw.get("effects", {})),
            sandbox=dict(raw.get("sandbox", {})),
            allow_restricted=bool(raw["eligibility"].get("allow_restricted", False)),
            digest=_digest(path),
        )
    except KeyError as exc:
        raise ContractError(f"{path}: missing {exc}") from exc


def load_repos(root: Path | None = None) -> dict[str, RepoSpec]:
    raw = tomllib.loads(((root or home()) / "governance" / "repos.toml").read_text())
    out = {}
    for name, r in raw["repos"].items():
        floor = r.get("data_class_floor", "public")
        if floor not in DATA_CLASSES:
            raise ContractError(f"{name}: data_class_floor must be one of {DATA_CLASSES}")
        out[name] = RepoSpec(name=name, path=Path(r["path"]), main=r.get("main", "main"),
                             test_cmd=r["test_cmd"], check_cmd=r["check_cmd"],
                             worktree_root=Path(r["worktree_root"]),
                             setup_cmd=r.get("setup_cmd", ""),
                             protected_paths=tuple(r.get("protected_paths", ())),
                             data_class_floor=floor,
                             routing={k: float(v) for k, v in r.get("routing", {}).items()},
                             gate_jobs=_gate_jobs(name, r.get("gate_jobs", ())),
                             deploy=_deploy(name, r["deploy"]) if "deploy" in r else None,
                             landing=_landing(name, r.get("landing", "local")))
    return out


def load_release(release_dir: Path) -> WorkRelease:
    raw = tomllib.loads((release_dir / "release.toml").read_text())
    acc = raw.get("acceptance", {})
    try:
        return WorkRelease(
            id=raw["id"], repo=raw["repo"], base_sha=raw["base_sha"], title=raw["title"],
            outcome=raw["outcome"], task_class=raw["task_class"], size=raw["size"],
            data_class=raw["data_class"], scope_paths=tuple(raw["scope"]["paths"]),
            acceptance=Acceptance(exec=tuple(acc.get("exec", ())), files=tuple(acc.get("files", ())),
                                  fail_on_base=bool(acc.get("fail_on_base", True))),
            eligible_lanes=tuple(raw.get("eligible_lanes", ("implement",))),
            draft=bool(raw.get("draft", False)),
            work=str(raw.get("work", "")),
            work_complete=bool(raw.get("work_complete", False)),
            constraints=tuple(raw.get("constraints", ())),
            escalate_when=tuple(raw.get("escalate_when", ())),
            allow_deps=bool(raw.get("allow_deps", False)),
            allow_test_edits=bool(raw.get("allow_test_edits", False)),
            revision=int(raw.get("revision", 1)),
            release_dir=str(release_dir),
        )
    except KeyError as exc:
        raise ContractError(f"{release_dir}: missing {exc}") from exc


def load_releases(root: Path | None = None) -> list[WorkRelease]:
    base = (root or home()) / "backlog"
    return [load_release(p.parent) for p in sorted(base.glob("*/release.toml"))]
