"""Contract v1: the event envelope and the payloads the control plane accepts.

Governance path. Lanes may propose changes here only through interactive review.

Two event families carry capacity (``usage.recorded``, ``window.observed``) and
one revision family carries policy (``policy.revised`` with kind ``lane`` or
``allocation``). Every other view is a projection over the log.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

CONTRACT_VERSION = "lanectl.event/v1"

ITEM_STATES = (
    "ready", "claimed", "implemented", "gated", "candidate",
    "in-train", "landed", "rejected", "requeued", "parked",
)
SIZE_CLASSES = ("S", "M", "L")
DATA_CLASSES = ("public", "restricted")
DECISIONS = ("candidate", "rejected", "parked", "landed")

# event type -> required payload keys
EVENT_TYPES: dict[str, tuple[str, ...]] = {
    "release.published": ("release_id", "revision"),
    "item.claimed": ("attempt_id", "lane", "model", "worker"),
    "attempt.finished": ("attempt_id", "outcome", "exit_code", "head_sha"),
    "gate.result": ("attempt_id", "gate", "passed", "violations"),
    "decision.recorded": ("attempt_id", "decision", "reasons", "rules_revision"),
    "experiment.recorded": ("attempt_id", "model", "worker", "task_class", "decision", "elapsed_s"),
    "usage.recorded": ("provider", "source", "units"),
    "window.observed": ("provider", "window", "observed"),
    "policy.revised": ("kind", "revision", "digest"),
    "train.built": ("train_id", "base_sha", "attempts", "passed"),
    "item.landed": ("attempt_id", "train_id", "fix_commits"),
    "item.parked": ("reason",),
    "item.requeued": ("reason",),
    "integrator.fix": ("attempt_id", "commit", "fix_class"),
}
FIX_CLASSES = ("spec-gap", "model-error", "gate-gap")

_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")


class ContractError(ValueError):
    pass


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_id(name: str, value: str) -> str:
    if not isinstance(value, str) or not _ID.match(value):
        raise ContractError(f"{name} must match {_ID.pattern}: {value!r}")
    return value


def make_event(etype: str, data: dict, *, item_id: str | None = None, ts: str | None = None) -> dict:
    validate_event_parts(etype, data, item_id)
    return {"schema": CONTRACT_VERSION, "ts": ts or utcnow(), "type": etype,
            "item_id": item_id, "data": data}


def validate_event_parts(etype: str, data: dict, item_id: str | None) -> None:
    if etype not in EVENT_TYPES:
        raise ContractError(f"unknown event type {etype!r}")
    if not isinstance(data, dict):
        raise ContractError("data must be an object")
    missing = [k for k in EVENT_TYPES[etype] if k not in data]
    if missing:
        raise ContractError(f"{etype} missing {missing}")
    if item_id is not None:
        check_id("item_id", item_id)
    if etype == "decision.recorded" and data["decision"] not in DECISIONS:
        raise ContractError(f"bad decision {data['decision']!r}")
    if etype == "integrator.fix" and data["fix_class"] not in FIX_CLASSES:
        raise ContractError(f"bad fix_class {data['fix_class']!r}")
    if etype == "usage.recorded" and not isinstance(data["units"], dict):
        raise ContractError("usage units must be an object of unit -> number")


def validate_event(event: dict) -> dict:
    if event.get("schema") != CONTRACT_VERSION:
        raise ContractError(f"schema must be {CONTRACT_VERSION}")
    if not isinstance(event.get("ts"), str):
        raise ContractError("ts must be a string")
    validate_event_parts(event.get("type"), event.get("data"), event.get("item_id"))
    return event


@dataclass(frozen=True)
class Acceptance:
    exec: tuple[str, ...]                 # commands that must exit 0 in the worktree
    files: tuple[str, ...] = ()           # planner-written files, relative to the release dir
    fail_on_base: bool = True             # acceptance files must fail on base_sha


@dataclass(frozen=True)
class WorkRelease:
    """A ready item. Planner-authored; never inside a worker's write scope."""
    id: str
    repo: str                             # name from governance/repos.toml
    base_sha: str
    title: str
    outcome: str
    task_class: str
    size: str
    data_class: str
    scope_paths: tuple[str, ...]
    acceptance: Acceptance
    eligible_lanes: tuple[str, ...] = ("implement",)
    constraints: tuple[str, ...] = ()
    escalate_when: tuple[str, ...] = ()
    allow_deps: bool = False
    allow_test_edits: bool = False
    revision: int = 1
    release_dir: str = ""                 # set by the loader

    def __post_init__(self) -> None:
        check_id("id", self.id)
        if self.size not in SIZE_CLASSES:
            raise ContractError(f"size must be one of {SIZE_CLASSES}")
        if self.data_class not in DATA_CLASSES:
            raise ContractError(f"data_class must be one of {DATA_CLASSES}")


@dataclass(frozen=True)
class LaneRevision:
    """A RecipeRevision for one lane. Read from governance/lanes/<lane>.toml."""
    lane: str
    revision: int
    size_max: str
    routing: dict[str, float]             # model -> weight; worker resolved from model prefix
    max_attempts: int
    retry: str                            # "different_model" | "same_model"
    caps: dict[str, int]                  # concurrency, items_per_day, accepted_unlanded_max
    size_budget_lines: dict[str, int]
    protected_paths: tuple[str, ...]
    dependency_manifests: tuple[str, ...]
    test_globs: tuple[str, ...]
    forbidden_added_patterns: tuple[str, ...]
    external_models: tuple[str, ...]      # models that leave the estate (data boundary)
    timeout_s: int = 2700
    effects: dict[str, str] = field(default_factory=dict)
    digest: str = ""
