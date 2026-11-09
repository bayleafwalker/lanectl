"""Coverage of decision records against independent denominators.

A decision class's coverage is only meaningful against an expected count derived
from facts other than the records themselves: claims, requeues, parks, burn plans
and evaluations.  ``coverage`` joins those independent denominators to the
``lane.decision`` records that answer them, so a class with no records reads as
zero coverage rather than as no evidence.  ``refusal`` has no independent
denominator (refusals are only known from the records), so its expected count
and coverage stay unknown.
"""
from __future__ import annotations

from .contracts import LANE_DECISION_KINDS

#: Decision kinds reported; refusals are recorded but have no denominator.
_KINDS = (*LANE_DECISION_KINDS, "refusal")


def _first_decision_ts(events: list[dict]) -> str | None:
    """Timestamp of the first ``lane.decision``; earlier history predates the contract."""
    for ev in events:
        if isinstance(ev, dict) and ev.get("type") == "lane.decision":
            ts = ev.get("ts")
            if isinstance(ts, str) and ts:
                return ts
    return None


def coverage(events: list[dict]) -> dict[str, dict]:
    """Count expected versus recorded decisions for every kind (pure).

    Only events at or after the first ``lane.decision`` count: records written
    before the contract existed have no corresponding decisions, so early
    history would otherwise dilute dispatch (and every other) coverage.
    """
    since = _first_decision_ts(events)
    expected: dict[str, int | None] = {kind: 0 for kind in _KINDS}
    expected["refusal"] = None
    recorded = {kind: 0 for kind in _KINDS}
    claimed: set[str] = set()
    dispatch_applied: set[str] = set()

    for ev in events:
        if not isinstance(ev, dict):
            continue
        if since is not None:
            ts = ev.get("ts")
            if not isinstance(ts, str) or ts < since:
                continue
        kind, data = ev.get("type"), ev.get("data")
        if not isinstance(data, dict):
            continue
        if kind == "item.claimed":
            attempt_id = data.get("attempt_id")
            if isinstance(attempt_id, str) and attempt_id:
                claimed.add(attempt_id)
        elif kind == "item.requeued":
            expected["rerun"] += 1
        elif kind == "item.parked":
            expected["escalation"] += 1
        elif kind == "burn.planned":
            expected["allocation"] += 1
        elif kind == "evaluation.recorded":
            expected["acceptance"] += 1
        elif kind == "lane.decision":
            phase = data.get("phase")
            if phase == "refused":
                recorded["refusal"] += 1
            if data.get("kind") == "dispatch" and phase == "applied":
                subject = data.get("subject")
                if isinstance(subject, dict):
                    attempt_id = subject.get("attempt_id")
                    if isinstance(attempt_id, str):
                        dispatch_applied.add(attempt_id)     # one per claimed attempt
            elif data.get("kind") == "rerun" and phase == "applied":
                recorded["rerun"] += 1
            elif data.get("kind") == "escalation" and phase == "applied":
                recorded["escalation"] += 1
            elif data.get("kind") == "allocation" and phase == "proposed":
                recorded["allocation"] += 1
            elif data.get("kind") == "acceptance":
                recorded["acceptance"] += 1

    expected["dispatch"] = len(claimed)
    recorded["dispatch"] = len(dispatch_applied & claimed)

    out: dict[str, dict] = {}
    for kind in _KINDS:
        exp, rec = expected[kind], recorded[kind]
        ratio = round(min(rec, exp) / exp, 3) if exp else None
        out[kind] = {"expected": exp, "recorded": rec, "coverage": ratio}
    out["_since"] = since
    return out


def _fmt_coverage(value: dict) -> list[str]:
    since = value.get("_since") or "-"
    lines = ["", f"decision_coverage (since {since}):"]
    for kind in sorted(k for k in value if k != "_since"):
        row = value[kind]
        exp = row.get("expected")
        ratio = row.get("coverage")
        lines.append(f"  {kind}: recorded={row.get('recorded', 0)} "
                     f"expected={'unknown' if exp is None else exp} "
                     f"coverage={'unknown' if ratio is None else f'{ratio:.3f}'}")
    return lines


def report_section():
    """Report section: decision-record coverage per kind."""
    return "decision_coverage", coverage, _fmt_coverage
