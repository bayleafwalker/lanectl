"""Decision rules over gate results. Governance path; bump RULES_REVISION on change."""
from __future__ import annotations

RULES_REVISION = "decision-rules/v1"


def decide(gates: dict[str, list[str]], worker_outcome: str, attempts_used: int,
           max_attempts: int) -> tuple[str, list[str], str]:
    """Return (decision, reasons, follow_up) where follow_up is requeue|park|none.

    - any protected-path violation  -> parked (never auto-accepted; interactive review)
    - worker escalated              -> parked
    - any other violation / failure -> rejected, requeued while attempts remain
    - all gates clean               -> candidate (preliminary acceptance)
    """
    reasons = [f"{g}: {v}" for g, vs in gates.items() for v in vs]
    if any(v.startswith("protected-path:") for vs in gates.values() for v in vs):
        return "parked", reasons or ["protected path touched"], "park"
    if worker_outcome == "escalated":
        return "parked", reasons + ["worker escalated"], "park"
    if worker_outcome != "done":
        reasons.append(f"worker outcome {worker_outcome}")
    if reasons:
        follow = "requeue" if attempts_used < max_attempts else "park"
        return "rejected", reasons, follow
    return "candidate", ["all gates passed"], "none"
