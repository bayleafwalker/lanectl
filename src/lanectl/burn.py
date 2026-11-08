"""Burn-down: spend expiring capacity before its window resets it.

``plan_burn`` is a pure planner over the capacity projection.  When a provider
window is about to expire it fills the remaining burnable headroom with the
oldest ready work whose policy estimates fit, while respecting the same WIP
caps admission enforces.  The ``lanectl burn`` command prints that plan,
records it, and can execute it item by item.
"""
from __future__ import annotations

import tomllib
from datetime import datetime, timezone

from . import runner
from .capacity import AllocationPolicy, PolicyError, parse_ts, project
from .config import home, load_lane, load_releases, load_repos
from .events import EventLog, project_items
from .ready import readiness

# Defaults mirror governance/allocation.toml; a policy without a [burn] table
# simply has no burn rules and never plans.
DEFAULT_START_WITHIN_S = 3600
DEFAULT_MIN_BURNABLE = 10000


def _burn_rules(policy_raw: dict) -> tuple[float, float] | None:
    burn = policy_raw.get("burn") if isinstance(policy_raw, dict) else None
    if not isinstance(burn, dict):
        return None
    try:
        start_within = float(burn.get("start_within_s", DEFAULT_START_WITHIN_S))
        min_burnable = float(burn.get("min_burnable", DEFAULT_MIN_BURNABLE))
    except (TypeError, ValueError):
        return None
    return start_within, min_burnable


def _slots(caps: dict, running: int, unlanded: int) -> int:
    try:
        concurrency = int(caps["concurrency"]) - int(running)
        accepted = int(caps["accepted_unlanded_max"]) - int(unlanded)
    except (KeyError, TypeError, ValueError):
        return 0
    return min(concurrency, accepted)


def plan_burn(events: list[dict], policy_raw: dict, now: datetime,
              ready: list[tuple[str, str]], caps: dict,
              running: int, unlanded: int) -> dict | None:
    """Plan a burn of expiring capacity, or return ``None``.

    ``ready`` is ``[(release_id, size)]`` in backlog order.  A window qualifies
    when it ends within ``burn.start_within_s`` and its projected burnable
    headroom is at least ``burn.min_burnable``.  Items are taken in order while
    their summed policy estimate fits the burnable headroom and the plan stays
    within ``min(concurrency - running, accepted_unlanded_max - unlanded)``.
    """
    rules = _burn_rules(policy_raw)
    if rules is None:
        return None
    start_within_s, min_burnable = rules

    slots = _slots(caps, running, unlanded)
    if slots <= 0:
        return None

    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    try:
        policy = AllocationPolicy.from_dict(policy_raw)
    except PolicyError:
        return None
    views = project(events, policy, now)

    for provider, spec in policy.providers.items():
        if not spec.expiring:
            continue
        provider_raw = policy_raw.get("providers", {}).get(provider, {})
        estimates = provider_raw.get("estimates", {})
        if not isinstance(estimates, dict):
            estimates = {}
        for window in spec.windows:
            view = views.get(provider, {}).get(window.name)
            if view is None:
                continue
            end = parse_ts(view.get("window_end"))
            if end is None:
                continue
            remaining_s = (end - now).total_seconds()
            if remaining_s > start_within_s:
                continue
            burnable = view.get("burnable", 0)
            if burnable < min_burnable:
                continue

            total = 0
            items: list[str] = []
            reasons = [
                f"window ends in {remaining_s:.0f}s (<= {start_within_s:g}s)",
                f"burnable {burnable} >= min {min_burnable:g}",
            ]
            for release_id, size in ready:
                if len(items) >= slots:
                    reasons.append(f"slot limit {slots} reached")
                    break
                estimate = estimates.get(size)
                if isinstance(estimate, bool) or not isinstance(estimate, (int, float)):
                    reasons.append(f"skip {release_id}: no policy estimate for size {size}")
                    continue
                if total + estimate > burnable:
                    reasons.append(
                        f"stop at {release_id}: {size} estimate {estimate} would exceed "
                        f"burnable {burnable} (used {total})"
                    )
                    break
                items.append(release_id)
                total += estimate
                reasons.append(f"{release_id}: {size} estimate {estimate} (sum {total}/{burnable})")

            if items:
                return {"provider": provider, "window": window.name,
                        "burnable": burnable, "items": items, "reasons": reasons}
    return None


def _load_policy_raw() -> dict | None:
    path = home() / "governance" / "allocation.toml"
    if not path.is_file():
        return None
    try:
        return tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        print(f"{path}: {exc}")
        return None


def _ready_items(lane, repos, events: list[dict]) -> list[tuple[str, str]]:
    """Releases in backlog order that are ready to admit now."""
    states = project_items(events)
    out: list[tuple[str, str]] = []
    for rel in load_releases():
        state = states[rel.id].state if rel.id in states else "ready"
        if state not in ("ready", "requeued"):
            continue
        if readiness(rel, lane, repos):
            continue
        out.append((rel.id, rel.size))
    return out


def register(sub) -> dict:
    p = sub.add_parser("burn", help="plan (and optionally execute) a burn of expiring capacity")
    p.add_argument("--record", action="store_true", help="append burn.planned to the event log")
    p.add_argument("--execute", action="store_true",
                   help="admit and execute the planned items one at a time")
    p.add_argument("--lane", default="implement")
    return {"burn": _cmd}


def _cmd(args, log: EventLog) -> int:
    policy_raw = _load_policy_raw()
    if policy_raw is None:
        print("no allocation policy (governance/allocation.toml); nothing to burn")
        return 0
    now = datetime.now(timezone.utc)
    lane, repos = load_lane(args.lane), load_repos()
    events = log.read()
    items = project_items(events)
    running = sum(1 for v in items.values() if v.state == "claimed")
    unlanded = sum(1 for v in items.values() if v.state in ("candidate", "in-train"))
    plan = plan_burn(events, policy_raw, now, _ready_items(lane, repos, events),
                     lane.caps, running, unlanded)
    if plan is None:
        print("no burn plan: no expiring window qualifies within the WIP caps")
        return 0

    print(f"burn {plan['provider']} {plan['window']}: burnable={plan['burnable']}")
    print(f"items: {', '.join(plan['items'])}")
    for reason in plan["reasons"]:
        print(f"  - {reason}")

    if args.record:
        with log.locked():
            log.append("burn.planned", {
                "provider": plan["provider"], "window": plan["window"],
                "burnable": plan["burnable"], "items": list(plan["items"]),
                "reasons": list(plan["reasons"]),
            })
        print("recorded burn.planned")

    if args.execute:
        for release_id in plan["items"]:
            claim = runner.admit(args.lane, log, only=release_id)
            if isinstance(claim, str):
                print(claim)
                break
            print(f"claimed {claim.attempt_id} -> {claim.model}", flush=True)
            print(runner.execute(claim, log), flush=True)
    return 0
