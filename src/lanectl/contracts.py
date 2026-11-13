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
WORK_REF = re.compile(r"[a-z0-9][a-z0-9-]*#[1-9][0-9]*")

EVENT_TYPES: dict[str, tuple[str, ...]] = {
    "release.published": ("release_id", "revision"),
    "release.publication.invalidated": ("release_id", "revision", "target_event_sha256", "reason", "evidence_ref"),
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
    # V1 (2026-11-10): the tracker item a landed release reports to. ok=False carries `error`;
    # a failed sync never fails the land. Optional `pending_close`: true when the release is
    # work_complete but its repo lands by PR, so the close waits for the merge.
    "work.synced": ("work", "train_id", "closed", "ok"),
    "item.parked": ("reason",),
    "item.requeued": ("reason",),
    "integrator.fix": ("attempt_id", "commit", "fix_class"),
    # v1 additive extension (planner, 2026-11-08) for ladder stages 2-5.
    "admission.shadow": ("static", "capacity", "agree", "reasons"),          # S2 capacity admission
    "evaluation.recorded": ("attempt_id", "evaluator", "verdict", "rules_revision"),  # S3 evaluator
    "landing.planned": ("train_id", "plan", "by"),                            # S4 shadow landing
    "triage.proposed": ("source", "fingerprint", "summary"),                  # S4 triage emitters
    "burn.planned": ("provider", "window", "burnable", "items"),              # S5 burn-down
    # v1 additive extension (planner, 2026-11-09): decision records and capacity feedback
    # (docs/plans/2026-11-09-decision-records-and-capacity-feedback.md). lane.decision is not
    # decision.recorded (gate/candidate vocabulary) and not Vuoro's authoritative Decision.
    "lane.decision": ("decision_id", "kind", "phase", "chosen", "mechanism", "policy_revision"),
    "capacity.observed": ("provider", "pool", "source", "unit", "basis", "observed_at"),
    "capacity.reserved": ("reservation_id", "provider", "pool", "unit", "amount", "attempt_id"),
    "capacity.reconciled": ("reservation_id", "actual", "outcome"),
    # v1 additive extension (planner, 2026-11-10): stage 3 dev train deploys
    # (docs/plans/2026-11-10-stage3-gate-jobs-and-train-deploys.md).
    "train.deployed": ("train_id", "repo", "namespace", "passed", "expires_at"),
    "train.torn_down": ("train_id", "namespace", "reason", "passed"),
}
LANE_DECISION_KINDS = ("dispatch", "rerun", "escalation", "allocation", "acceptance")
LANE_DECISION_PHASES = ("proposed", "applied", "refused", "expired", "superseded")
CAPACITY_BASES = ("measured", "estimated", "unknown")
RECONCILE_OUTCOMES = ("completed", "recovered", "released")
FIX_CLASSES = ("spec-gap", "model-error", "gate-gap")
TEARDOWN_REASONS = ("expired", "landed", "superseded", "deploy-failed", "manual")

_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")


class ContractError(ValueError):
    pass


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_id(name: str, value: str) -> str:
    if not isinstance(value, str) or not _ID.match(value):
        raise ContractError(f"{name} must match {_ID.pattern}: {value!r}")
    return value


def parse_evidence_ref(ref):
    """Parse a committed evidence reference without accessing Git."""
    match = re.fullmatch(r"git:([0-9a-f]{40}):(.+)", ref) if isinstance(ref, str) else None
    if not match:
        raise ContractError("evidence_ref must be git:<full commit>:<relative path>")
    commit, path = match.groups()
    if (path.startswith("/") or any(ord(ch) < 32 or ord(ch) == 127 for ch in path)
            or any(part in ("", ".", "..") for part in path.split("/"))):
        raise ContractError("evidence_ref path must be a safe relative path")
    return commit, path


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
    if etype == "release.published" and "provenance" in data:
        if data["provenance"] not in ("guarded-publish", "nondraft-observation"):
            raise ContractError("invalid publication provenance")
    if etype == "release.publication.invalidated":
        check_id("release_id", data["release_id"])
        if item_id != data["release_id"]:
            raise ContractError("invalidation item_id must match release_id")
        if type(data["revision"]) is not int or data["revision"] < 1:
            raise ContractError("invalidation revision must be positive")
        if not isinstance(data["target_event_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", data["target_event_sha256"]):
            raise ContractError("invalid target event sha256")
        if not isinstance(data["reason"], str) or not data["reason"].strip():
            raise ContractError("invalidation reason must be nonempty")
        parse_evidence_ref(data["evidence_ref"])
    if etype == "decision.recorded" and data["decision"] not in DECISIONS:
        raise ContractError(f"bad decision {data['decision']!r}")
    if etype == "integrator.fix" and data["fix_class"] not in FIX_CLASSES:
        raise ContractError(f"bad fix_class {data['fix_class']!r}")
    if etype == "usage.recorded" and not isinstance(data["units"], dict):
        raise ContractError("usage units must be an object of unit -> number")
    if etype == "lane.decision":
        if data["kind"] not in LANE_DECISION_KINDS:
            raise ContractError(f"bad lane.decision kind {data['kind']!r}")
        if data["phase"] not in LANE_DECISION_PHASES:
            raise ContractError(f"bad lane.decision phase {data['phase']!r}")
    if etype == "capacity.observed" and data["basis"] not in CAPACITY_BASES:
        raise ContractError(f"bad capacity basis {data['basis']!r}")
    if etype == "capacity.reconciled" and data["outcome"] not in RECONCILE_OUTCOMES:
        raise ContractError(f"bad reconcile outcome {data['outcome']!r}")


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
    draft: bool = False                   # a draft is never ready (lanectl backlog publish)
    work: str = ""                        # sprintctl item "<repo>#<id>" this release delivers
    work_complete: bool = False           # landing closes the item (else only notes it)
    release_dir: str = ""                 # set by the loader

    def __post_init__(self) -> None:
        check_id("id", self.id)
        if self.size not in SIZE_CLASSES:
            raise ContractError(f"size must be one of {SIZE_CLASSES}")
        if self.data_class not in DATA_CLASSES:
            raise ContractError(f"data_class must be one of {DATA_CLASSES}")
        if self.work and not WORK_REF.fullmatch(self.work):
            raise ContractError(f"work must look like <repo>#<id>, got {self.work!r}")
        if self.work_complete and not self.work:
            raise ContractError("work_complete needs work")


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
    sandbox: dict = field(default_factory=dict)     # see lanectl.sandbox
    # Restricted work (release data_class or repo floor) is eligible only in a lane that sets
    # [eligibility] allow_restricted = true; such lanes route first-party models and are run by
    # hand, never by the tick timer (operator direction 2026-11-10).
    allow_restricted: bool = False
    digest: str = ""
