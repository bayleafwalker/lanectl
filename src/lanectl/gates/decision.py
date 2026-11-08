"""Decision rules over gate results. Governance path; bump RULES_REVISION on change."""
from __future__ import annotations

RULES_REVISION = "decision-rules/v3"


def decide(gates: dict[str, list[str]], worker_outcome: str, attempts_used: int,
           max_attempts: int, changed: bool = True) -> tuple[str, list[str], str]:
    """Return (decision, reasons, follow_up) where follow_up is requeue|requeue-infra|park|none.

    - worker failed and changed nothing -> rejected as infra; does not consume an
      attempt and trips the run-loop breaker (v2, after a wrapper bug burned a batch)

    - any protected-path violation  -> parked (never auto-accepted; interactive review)
    - worker escalated              -> parked
    - any other violation / failure -> rejected, requeued while attempts remain
    - all gates clean               -> candidate (preliminary acceptance)
    """
    if worker_outcome == "failed" and not changed:
        return "rejected", ["infra: worker failed without changing anything"], "requeue-infra"
    review = [f"{g}: {v}" for g, vs in gates.items() for v in vs if v.startswith("protected-review:")]
    reasons = [f"{g}: {v}" for g, vs in gates.items() for v in vs if not v.startswith("protected-review:")]
    if any(v.startswith("protected-path:") for vs in gates.values() for v in vs):
        return "parked", reasons or ["protected path touched"], "park"
    if worker_outcome == "escalated":
        return "parked", reasons + ["worker escalated"], "park"
    if worker_outcome != "done":
        reasons.append(f"worker outcome {worker_outcome}")
    if reasons:
        follow = "requeue" if attempts_used < max_attempts else "park"
        return "rejected", reasons, follow
    if review:   # v3: in-scope governance change, gates clean -> interactive review
        return "parked", ["review-required: all gates passed"] + review, "park"
    return "candidate", ["all gates passed"], "none"
