"""Operator (planner + integrator) cost per landed release.

Lane workers pay their own usage through the accounts the adapters report, but
the planner's and integrator's interactive spend (``source ==
"claude-code-interactive"``) is operator time.  This projection prices both
against the same published tables and divides by landed releases, so ADR 0001's
"pause if integrator cost per landed item exceeds doing it interactively" has a
number: ``operator_usd_per_landed`` next to ``lane_usd_per_landed``.
"""
from __future__ import annotations

from .costs import _load_policy_raw, _price_tables, price_usage

#: ``usage.recorded`` source that is the operator, not a lane worker.
_OPERATOR_SOURCE = "claude-code-interactive"


def _new_release() -> dict:
    return {"lane_usd": 0.0, "operator_usd": 0.0, "landed": False}


def operator_cost(events: list[dict], policy_raw: dict) -> dict:
    """Per-release lane and operator spend, divided by landed releases.

    Operator usage is any ``usage.recorded`` whose ``data.source`` is
    ``claude-code-interactive``; every other usage with an ``item_id`` is lane
    usage.  Each event is priced against every provider's table (the first that
    prices it wins); an event no table prices counts in ``unpriced_events`` and
    adds nothing.  Operator usage without an ``item_id`` is unattributed.
    """
    tables = _price_tables(policy_raw)
    releases: dict[str, dict] = {}
    unattributed = 0.0
    unpriced = 0

    for ev in events:
        if not isinstance(ev, dict):
            continue
        kind, data, item_id = ev.get("type"), ev.get("data"), ev.get("item_id")
        if not isinstance(data, dict):
            continue
        if kind == "item.landed":
            if isinstance(item_id, str) and item_id:
                releases.setdefault(item_id, _new_release())["landed"] = True
            continue
        if kind != "usage.recorded":
            continue
        operator = data.get("source") == _OPERATOR_SOURCE
        if not operator and not isinstance(item_id, str):
            continue                    # lane usage without an item is not attributed
        model = data.get("model")
        if not isinstance(model, str) or not model:
            continue                    # unpriced by omission, as cost_summary does
        usd = None
        for prices in tables:
            usd = price_usage(data.get("units") or {}, model, ev.get("ts"), prices)
            if usd is not None:
                break
        if usd is None:
            unpriced += 1
            continue
        if operator:
            if isinstance(item_id, str) and item_id:
                releases.setdefault(item_id, _new_release())["operator_usd"] += usd
            else:
                unattributed += usd
        else:
            releases.setdefault(item_id, _new_release())["lane_usd"] += usd

    landed = sum(1 for row in releases.values() if row["landed"])
    if landed:
        lane_per_landed = sum(r["lane_usd"] for r in releases.values() if r["landed"]) / landed
        operator_per_landed = sum(r["operator_usd"] for r in releases.values()
                                  if r["landed"]) / landed
    else:
        lane_per_landed = operator_per_landed = None

    return {
        "releases": releases,
        "landed": landed,
        "lane_usd_per_landed": lane_per_landed,
        "operator_usd_per_landed": operator_per_landed,
        "unattributed_operator_usd": unattributed,
        "unpriced_events": unpriced,
    }


def _report(events: list[dict]) -> dict | None:
    """Report value: operator cost, or ``None`` when governance publishes no prices."""
    policy_raw = _load_policy_raw()
    if not _price_tables(policy_raw):
        return None
    return operator_cost(events, policy_raw)


def _fmt_operator_cost(result: dict | None) -> list[str]:
    lines = ["", "operator_cost (estimate from published prices):"]
    if result is None:
        lines.append("  no price table")
        return lines
    lane = "-" if result["lane_usd_per_landed"] is None \
        else f"{result['lane_usd_per_landed']:.2f}"
    operator = "-" if result["operator_usd_per_landed"] is None \
        else f"{result['operator_usd_per_landed']:.2f}"
    lines.append(f"  landed={result['landed']} lane_usd/landed={lane} "
                 f"operator_usd/landed={operator} "
                 f"unattributed_operator_usd={result['unattributed_operator_usd']:.2f} "
                 f"unpriced={result['unpriced_events']}")
    return lines


def report_section():
    """Report section: operator cost per landed release."""
    return "operator_cost", _report, _fmt_operator_cost
