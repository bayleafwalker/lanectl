"""Bounded learned routing within a reviewed class and model allowlist.

The eligible input is already filtered by data class and retry policy. Learning
cannot introduce a provider, model or task class. Without sufficient evidence
for every eligible model the reviewed static allocation remains authoritative.
"""
from __future__ import annotations

import math

from . import capacity, learning


def effective_weights(events, eligible: dict[str, float], task_class: str,
                      policy: dict) -> dict[str, float]:
    original = dict(eligible)
    if task_class not in policy.get("adaptive_classes", ()):
        return original
    change = float(policy.get("max_relative_change", .25))
    floor = float(policy.get("min_weight", .05))
    ceiling = float(policy.get("max_weight", 1.))
    minimum = int(policy.get("min_evidence", 5))
    if (not all(math.isfinite(v) for v in (change, floor, ceiling))
            or not 0 <= change <= 1 or not 0 < floor <= ceiling or minimum < 1):
        raise ValueError("invalid adaptive routing bounds")
    if not original:
        return original
    evidence = learning.posterior(events, policy)
    if any(evidence.get((model, task_class), {}).get("ruled", 0) < minimum
           for model in original):
        return original
    proposed = learning.suggest(events, policy, original, task_class)
    result = {}
    for model, weight in original.items():
        value = float(proposed.get(model, weight))
        if not math.isfinite(value) or value <= 0:
            raise ValueError("invalid learned weight")
        low, high = max(floor, weight * (1 - change)), min(ceiling, weight * (1 + change))
        if low > high:
            raise ValueError("static weight outside adaptive bounds")
        result[model] = round(max(low, min(high, value)), 6)
    return result


def admission(events, policy, now, provider, size, model, *, enforce=False):
    """Enforce every qualified applicable fixed window under the claim lock.

    Observations must cover the account pool and exact consumption interval.
    Host totals, estimated values, unknown resets and stale/future observations
    retain static admission. A measured exhausted window still blocks even when
    another applicable window is unknown. Model limits conservatively charge
    pool totals and all in-flight reservations unless better scoped inputs exist.
    """
    result = {"decision": "admit", "basis": "unknown", "reasons": []}
    if not enforce or policy is None or provider not in policy.providers:
        result["reasons"].append("static admission retained")
        return result
    now = capacity._as_utc(now)
    spec = policy.providers[provider]
    for observed, seen, data in capacity._capacity_rows(events, provider, spec.pool, "denial"):
        reset = capacity.parse_ts(data.get("reset_at"))
        if (observed <= now and seen <= now and data.get("basis") == "measured"
                and data.get("unit") == spec.unit
                and data.get("model") in (None, model)
                and (reset is None or reset > now)):
            return {"decision": "block", "basis": "measured",
                    "reasons": ["provider denial remains active"]}
    estimate = capacity.estimate(events, policy, provider, size)
    if estimate is None or spec.freshness_s is None:
        result["reasons"].append("unknown estimate or observation freshness")
        return result
    applicable = [w for w in spec.windows if not w.models or model in w.models]
    known = 0
    for window in applicable:
        anchor = capacity._observed_anchor(events, provider, window.name, window.anchor)
        if window.budget_basis != "verified" or anchor is None:
            continue
        start, end = capacity._window_bounds(now, anchor, window.length_s)
        rows = []
        for observed, seen, data in capacity._capacity_rows(events, provider, spec.pool, "cumulative"):
            value = data.get("value")
            if (data.get("basis") != "measured" or data.get("scope") not in ("account", "pool")
                    or data.get("model") or data.get("models")
                    or data.get("unit") != spec.unit
                    or capacity.parse_ts(data.get("window_start")) != start
                    or not start <= observed <= now or seen > now
                    or (now - observed).total_seconds() > spec.freshness_s
                    or isinstance(value, bool) or not isinstance(value, (float, int))
                    or not math.isfinite(value) or value < 0):
                continue
            rows.append((observed, seen, data))
        if not rows:
            continue
        known += 1
        observed, _, data = rows[-1]
        # Subsequent ledger rows consume additional capacity, without counting
        # the cumulative snapshot's already-covered interval a second time.
        after = sum(amount for ts, amount, _, _ in capacity._usage_rows(events, provider, spec.unit)
                    if observed < ts <= now)
        closed = {ev.get("data", {}).get("reservation_id") for ev in events
                  if ev.get("type") == "capacity.reconciled"}
        reservations = {}
        for ev in events:
            reservation = ev.get("data", {})
            if (ev.get("type") == "capacity.reserved" and reservation.get("pool") == spec.pool
                    and reservation.get("unit") == spec.unit
                    and reservation.get("reservation_id") not in closed):
                reservations[reservation["reservation_id"]] = reservation["amount"]
        held = sum(reservations.values())
        view = capacity.project(events, policy, now)[provider][window.name]
        free = window.budget - data["value"] - after - held - view["reserved_effective"]
        if free < estimate:
            return {"decision": "block", "basis": "measured",
                    "reasons": [f"{window.name}: available {free} below estimate {estimate}"]}
    if applicable and known == len(applicable):
        result["basis"] = "measured"
    result["reasons"].append(f"qualified windows {known}/{len(applicable)}")
    return result
