"""Load governance (lanes, repos) and backlog (WorkReleases) from LANECTL_HOME.

LANECTL_HOME is a checkout of this repository's main branch. Lanes write only to
lane/* branches in worktrees, so the governance they are judged by is never in
their write scope. When LANECTL_HOME is unset the checkout is found by walking up
from the working directory, so an installed lanectl works inside a checkout.
"""
from __future__ import annotations

import hashlib
import os
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
                             routing={k: float(v) for k, v in r.get("routing", {}).items()})
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
