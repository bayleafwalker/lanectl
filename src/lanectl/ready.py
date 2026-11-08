"""Definition of Ready: decides lane eligibility deterministically.

Governance path. Returns reasons, never a judgement call.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .adapters import worker_for
from .config import RepoSpec
from .contracts import SIZE_CLASSES, LaneRevision, WorkRelease

_SHA = re.compile(r"^[0-9a-f]{40}$")


def readiness(rel: WorkRelease, lane: LaneRevision, repos: dict[str, RepoSpec]) -> list[str]:
    """Empty list = ready for this lane. Each string is a blocking reason."""
    r: list[str] = []
    if lane.lane not in rel.eligible_lanes:
        r.append(f"lane {lane.lane} not in eligible_lanes")
    if SIZE_CLASSES.index(rel.size) > SIZE_CLASSES.index(lane.size_max):
        r.append(f"size {rel.size} exceeds lane size_max {lane.size_max}")
    if not rel.acceptance.exec:
        r.append("acceptance.exec is empty")
    if not rel.scope_paths:
        r.append("scope.paths is empty")
    if not rel.outcome.strip():
        r.append("outcome is empty")
    if not _SHA.match(rel.base_sha):
        r.append("base_sha must be a full 40-hex commit")
    repo = repos.get(rel.repo)
    if repo is None:
        r.append(f"repo {rel.repo!r} not in governance/repos.toml")
    elif _SHA.match(rel.base_sha):
        ok = subprocess.run(["git", "-C", str(repo.path), "cat-file", "-e", f"{rel.base_sha}^{{commit}}"],
                            capture_output=True).returncode == 0
        if not ok:
            r.append("base_sha not found in repo")
    for f in rel.acceptance.files:
        if not (Path(rel.release_dir) / "files" / f).is_file():
            r.append(f"acceptance file missing: files/{f}")
    weights = eligible_models(rel, lane, repo)
    if not any(w > 0 for w in weights.values()):
        if rel.data_class == "restricted" and all(m in lane.external_models for m in lane.routing):
            r.append("restricted data_class but every routed model is external")
        r.append("no eligible model")
    return r


def eligible_models(rel: WorkRelease, lane: LaneRevision,
                    repo: RepoSpec | None = None) -> dict[str, float]:
    """Routing weights after the repo overlay and the data boundary are applied.

    A repo routing table replaces the lane's weights; an empty table keeps the
    lane's.  The effective data class is the stricter of the release's own class
    and the repo's floor; restricted releases are an allowlist: only first-party
    (Claude) models that are not external survive.  A model no adapter can map is
    dropped rather than routed.
    """
    routing = dict(repo.routing) if repo is not None and repo.routing else dict(lane.routing)
    restricted = rel.data_class == "restricted" or (
        repo is not None and repo.data_class_floor == "restricted")
    if restricted:
        return {m: w for m, w in routing.items()
                if m not in lane.external_models and _first_party(m)}
    return routing


def _first_party(model: str) -> bool:
    """True only when the model is served by the first-party Claude adapter."""
    try:
        return worker_for(model) == "claude"
    except ValueError:
        return False
