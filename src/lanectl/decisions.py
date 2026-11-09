"""Compact ``lane.decision`` records for the runner.

One ``runner.admit`` call is one dispatch cycle.  A claim records the decision
twice (``proposed`` then ``applied``); a refused cycle records one ``refused``
record.  The gate decision that follows an attempt records a ``rerun`` or
``escalation`` applied record alongside ``item.requeued``/``item.parked``.

Records are references, not copied payloads: release, lane and attempt identity
plus the eligible weights the deterministic hash chose from.  The weighted hash
is reproducible from its inputs, so its selection probabilities are 1.0 for the
chosen model and 0.0 for the rest -- never an invented propensity.  Every
encoded line is kept within the 2 KiB budget.
"""
from __future__ import annotations

import json
import uuid

from .contracts import LaneRevision, WorkRelease, make_event, utcnow

MAX_RECORD_BYTES = 2048
MECHANISM_DISPATCH = "weighted-hash/v1"
MECHANISM_CAPS = "static-caps/v1"
MECHANISM_GATES = "gates"
MECHANISM_EVALUATOR = "evaluator-rules"
MECHANISM_INTEGRATOR = "integrator"
MECHANISM_REAPER = "reaper/v2"


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def new_cycle_id() -> str:
    """Identity of one admission cycle (one ``runner.admit`` call)."""
    return _new_id("cyc")


def policy_revision(lane: LaneRevision) -> str:
    return f"lane/{lane.lane}@{lane.revision}"


def basis(lane: LaneRevision, rel: WorkRelease) -> list[str]:
    return [f"release:{rel.id}@{rel.revision}", f"lane:{lane.lane}@{lane.revision}"]


def _clip(value: object, limit: int) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[:max(0, limit - 3)] + "..."


def _encoded(event: dict) -> int:
    return len(json.dumps(event, sort_keys=True, separators=(",", ":")).encode())


def _append(log, data: dict, *, item_id: str | None) -> None:
    """Append a validated record, shrinking reasons until the line fits."""
    data = dict(data)
    for limit in (200, 120, 60, 20, 0):
        event = make_event("lane.decision", data, item_id=item_id)
        if _encoded(event) <= MAX_RECORD_BYTES:
            log.append("lane.decision", data, item_id=item_id)
            return
        if "reasons" not in data:
            break
        data["reasons"] = [_clip(r, limit) for r in data.get("reasons", [])][:8]
    log.append("lane.decision", data, item_id=item_id)


def dispatch(log, *, lane: LaneRevision, rel: WorkRelease, attempt_id: str, cycle_id: str,
             model: str, alternatives: dict[str, float]) -> str:
    """Record proposed then applied dispatch records; return the applied id."""
    snapshot = {
        "kind": "dispatch",
        "chosen": model,
        "mechanism": MECHANISM_DISPATCH,
        "policy_revision": policy_revision(lane),
        "subject": {"item_id": rel.id, "attempt_id": attempt_id},
        "cycle_id": cycle_id,
        "snapshot_ts": utcnow(),
        "basis": basis(lane, rel),
        "alternatives": dict(alternatives),
        "probabilities": {m: 1.0 if m == model else 0.0 for m in alternatives},
    }
    proposed_id = _new_id("dec")
    _append(log, {"decision_id": proposed_id, "phase": "proposed", **snapshot}, item_id=rel.id)
    applied_id = _new_id("dec")
    _append(log, {"decision_id": applied_id, "phase": "applied", "proposal_id": proposed_id,
                  **snapshot}, item_id=rel.id)
    return applied_id


def refused(log, *, lane: LaneRevision, cycle_id: str, reasons: list[str],
            item_id: str | None = None) -> None:
    """Record a cycle the static caps or eligibility refused."""
    _append(log, {
        "decision_id": _new_id("dec"),
        "kind": "dispatch",
        "phase": "refused",
        "chosen": None,
        "mechanism": MECHANISM_CAPS,
        "policy_revision": policy_revision(lane),
        "cycle_id": cycle_id,
        "snapshot_ts": utcnow(),
        "basis": [f"lane:{lane.lane}@{lane.revision}"],
        "reasons": list(reasons),
    }, item_id=item_id)


def transition(log, *, lane: LaneRevision, rel: WorkRelease, attempt_id: str,
               follow: str, reasons: list[str]) -> str | None:
    """Record the applied gate follow-up (rerun or escalation), if any."""
    if follow == "park":
        kind, chosen = "escalation", "park"
    elif follow.startswith("requeue"):
        kind, chosen = "rerun", "requeue"
    else:
        return None
    decision_id = _new_id("dec")
    _append(log, {
        "decision_id": decision_id,
        "kind": kind,
        "phase": "applied",
        "chosen": chosen,
        "mechanism": MECHANISM_GATES,
        "policy_revision": policy_revision(lane),
        "subject": {"item_id": rel.id, "attempt_id": attempt_id},
        "snapshot_ts": utcnow(),
        "basis": basis(lane, rel),
        "reasons": list(reasons),
    }, item_id=rel.id)
    return decision_id


def acceptance_proposed(log, *, item_id: str, attempt_id: str, chosen: str,
                        policy_revision: str, reasons: list[str]) -> str:
    """Record the evaluator's preliminary acceptance verdict (one per evaluation)."""
    decision_id = _new_id("dec")
    _append(log, {
        "decision_id": decision_id,
        "kind": "acceptance",
        "phase": "proposed",
        "chosen": chosen,
        "mechanism": MECHANISM_EVALUATOR,
        "policy_revision": policy_revision,
        "subject": {"item_id": item_id, "attempt_id": attempt_id},
        "snapshot_ts": utcnow(),
        "reasons": list(reasons),
    }, item_id=item_id)
    return decision_id


def latest_acceptance_proposal(events: list[dict], attempt_id: str) -> str | None:
    """The most recent proposed acceptance decision for *attempt_id*, if any."""
    latest = None
    for ev in events:
        data = ev.get("data") if isinstance(ev, dict) else None
        if not isinstance(data, dict) or ev.get("type") != "lane.decision":
            continue
        if data.get("kind") != "acceptance" or data.get("phase") != "proposed":
            continue
        subject = data.get("subject")
        if isinstance(subject, dict) and subject.get("attempt_id") == attempt_id:
            latest = data.get("decision_id")
    return latest


def acceptance_applied(log, *, item_id: str, attempt_id: str,
                       proposal_id: str | None = None) -> str:
    """Record the integrator's applied acceptance; links the proposal it applied."""
    decision_id = _new_id("dec")
    data = {
        "decision_id": decision_id,
        "kind": "acceptance",
        "phase": "applied",
        "chosen": "candidate",
        "mechanism": MECHANISM_INTEGRATOR,
        "policy_revision": MECHANISM_INTEGRATOR,
        "subject": {"item_id": item_id, "attempt_id": attempt_id},
        "snapshot_ts": utcnow(),
    }
    if proposal_id is not None:
        data["proposal_id"] = proposal_id
    _append(log, data, item_id=item_id)
    return decision_id


def follow_applied(log, *, item_id: str, attempt_id: str, follow: str,
                   mechanism: str, reasons: list[str]) -> str | None:
    """Record a non-gate applied rerun/escalation (integrator or reaper)."""
    if follow == "park":
        kind, chosen = "escalation", "park"
    elif follow.startswith("requeue"):
        kind, chosen = "rerun", "requeue"
    else:
        return None
    decision_id = _new_id("dec")
    _append(log, {
        "decision_id": decision_id,
        "kind": kind,
        "phase": "applied",
        "chosen": chosen,
        "mechanism": mechanism,
        "policy_revision": mechanism,
        "subject": {"item_id": item_id, "attempt_id": attempt_id},
        "snapshot_ts": utcnow(),
        "reasons": list(reasons),
    }, item_id=item_id)
    return decision_id
