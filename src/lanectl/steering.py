"""Bounded learned routing within a reviewed class and model allowlist.

The eligible input is already filtered by data class and retry policy. Learning
cannot introduce a provider, model or task class. Without sufficient evidence
for every eligible model the reviewed static allocation remains authoritative.
"""
from __future__ import annotations

import math

from . import learning


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
