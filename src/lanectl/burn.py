"""Burn-down: spend expiring capacity before its window resets it.

``check`` is the gate: placeholder budgets, unknown capacity and denied pools
never burn, and a freshly applied allocation holds a ``[allocation]`` dwell
until the burnable amount moves past the change threshold.  ``plan_burn`` is a
pure planner over the qualified capacity projection only, using measured
headroom (budget minus lane, outside-lane and in-flight spend).  When a provider
window is about to expire it fills that headroom with the oldest ready work
whose policy estimates fit, while respecting the same WIP caps admission
enforces.  ``execute_plan`` records the allocation decision, revalidates before
each item and correlates every applied item with the claim it dispatched.  The
``lanectl burn`` command prints that plan, records it, and can execute it.
"""
from __future__ import annotations

import math
import tomllib
import uuid
from datetime import datetime, timedelta, timezone

from . import runner
from .capacity import AllocationPolicy, PolicyError, format_ts, parse_ts, qualified
from .config import home, load_lane, load_releases, load_repos
from .events import EventLog, project_items
from .ready import readiness

# Defaults mirror governance/allocation.toml; a policy without a [burn] table
# simply has no burn rules and never plans.
DEFAULT_START_WITHIN_S = 3600
DEFAULT_MIN_BURNABLE = 10000
DEFAULT_MIN_DWELL_S = 0
DEFAULT_CHANGE_THRESHOLD = 0.0

MECHANISM_BURN = "burn-plan/v1"


def _as_utc(now: datetime) -> datetime:
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _tidy(value: float) -> int | float:
    return int(value) if float(value).is_integer() else value


def _policy_revision(policy_raw: dict) -> str:
    try:
        revision = int(policy_raw.get("revision", 0))
    except (AttributeError, TypeError, ValueError):
        revision = 0
    return f"allocation@{revision}"


def _observation_anchor(events: list[dict], provider: str, spec) -> datetime | None:
    """Start of the measured range from the latest cumulative pool observation.

    Unanchored policy windows are revalidated against that evidence rather than
    assuming an epoch grid, so the burn window matches what was actually
    measured.  Only fresh cumulative snapshots qualify, which :func:`check`
    already requires before planning.
    """
    pool = spec.pool or f"{provider}:default"
    latest: tuple[datetime, datetime] | None = None
    for ev in events:
        if not isinstance(ev, dict) or ev.get("type") != "capacity.observed":
            continue
        data = ev.get("data")
        if not isinstance(data, dict):
            continue
        if data.get("provider") != provider or data.get("pool") != pool:
            continue
        if data.get("value_kind") != "cumulative":
            continue
        start = parse_ts(data.get("window_start"))
        if start is None:
            continue
        seen = parse_ts(ev.get("ts")) or start
        if latest is None or seen >= latest[0]:
            latest = (seen, start)
    return latest[1] if latest is not None else None


def _burn_window_bounds(now: datetime, anchor: datetime | None,
                        length_s: int) -> tuple[datetime, datetime]:
    """The fixed-length burn window containing ``now`` (UTC-day base by default)."""
    base = anchor or now.replace(hour=0, minute=0, second=0, microsecond=0)
    length = timedelta(seconds=length_s)
    index = math.floor((now - base).total_seconds() / length_s)
    start = base + length * index
    return start, start + length


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


def _allocation_rules(policy_raw: dict) -> tuple[float, float]:
    """``[allocation]`` dwell seconds and fractional change threshold."""
    allocation = policy_raw.get("allocation") if isinstance(policy_raw, dict) else None
    if not isinstance(allocation, dict):
        return float(DEFAULT_MIN_DWELL_S), float(DEFAULT_CHANGE_THRESHOLD)
    try:
        dwell = float(allocation.get("min_dwell_s", DEFAULT_MIN_DWELL_S))
        threshold = float(allocation.get("change_threshold", DEFAULT_CHANGE_THRESHOLD))
    except (TypeError, ValueError):
        return float(DEFAULT_MIN_DWELL_S), float(DEFAULT_CHANGE_THRESHOLD)
    return max(0.0, dwell), max(0.0, threshold)


def _measured_burnable(policy: AllocationPolicy, views: dict,
                       provider: str) -> float | None:
    """Burnable headroom using admission's arithmetic, or None when unknown.

    ``budget - lane usage - outside-lane spend - in-flight reservations``: while
    the qualified basis is unknown (or a denial holds the pool) there is no
    measured figure and no capacity is assumed free.
    """
    spec = policy.providers[provider]
    view = views.get(provider) or {}
    outside = view.get("outside_lane")
    if view.get("basis") == "unknown" or view.get("denied") or outside is None:
        return None
    lane_used = float(view.get("lane_used") or 0.0)
    held = float(view.get("in_flight") or 0.0)
    best: float | None = None
    for window in spec.windows:
        value = float(window.budget) - lane_used - float(outside) - held
        value = max(0.0, value)
        best = value if best is None else max(best, value)
    return best


def _dwell_reasons(events: list[dict], policy: AllocationPolicy, views: dict,
                   policy_raw: dict, now: datetime) -> list[str]:
    min_dwell_s, threshold = _allocation_rules(policy_raw)
    if min_dwell_s <= 0:
        return []
    latest: tuple[datetime, float] | None = None
    for ev in events:
        if not isinstance(ev, dict) or ev.get("type") != "lane.decision":
            continue
        data = ev.get("data")
        if not isinstance(data, dict):
            continue
        if data.get("kind") != "allocation" or data.get("phase") != "applied":
            continue
        ts = parse_ts(ev.get("ts"))
        burnable = data.get("burnable")
        if ts is None or isinstance(burnable, bool) or not isinstance(burnable, (int, float)):
            continue
        if latest is None or ts >= latest[0]:
            latest = (ts, float(burnable))
    if latest is None:
        return []
    age = (now - latest[0]).total_seconds()
    if age >= min_dwell_s:
        return []
    current: float | None = None
    for provider, spec in policy.providers.items():
        if not spec.expiring:
            continue
        value = _measured_burnable(policy, views, provider)
        if value is not None:
            current = value if current is None else max(current, value)
    if current is None:
        return []
    recorded = latest[1]
    if abs(current - recorded) < threshold * max(abs(recorded), 1.0):
        return [f"dwell: the latest allocation was applied {age:.0f}s ago "
                f"(< {min_dwell_s:g}s) and the new burnable {_tidy(current)} differs from "
                f"its recorded {_tidy(recorded)} by less than {threshold:g}"]
    return []


def check(events: list[dict], policy_raw: dict, now: datetime) -> list[str]:
    """Reasons no burn may be planned now; ``[]`` when burning is allowed.

    A burn is only ever planned from measured, verified capacity: placeholder
    budgets, an ``unknown`` qualified basis and denied pools all block, and an
    applied allocation holds a minimum dwell while its burnable amount is
    unchanged.  A denial is always reported, even inside the dwell.
    """
    try:
        policy = AllocationPolicy.from_dict(policy_raw)
    except PolicyError as exc:
        return [f"invalid allocation policy: {exc}"]
    now = _as_utc(now)
    views = qualified(events, policy, now)
    reasons: list[str] = []
    for provider, spec in policy.providers.items():
        if not spec.expiring:
            continue
        for window in spec.windows:
            if window.budget_basis != "verified":
                reasons.append(
                    f"window {provider}/{window.name} budget basis is {window.budget_basis!r}: "
                    f"placeholder values never establish entitlement or burn capacity")
        view = views.get(provider) or {}
        if view.get("basis") == "unknown":
            stale = " (stale observation)" if view.get("stale") else ""
            reasons.append(f"capacity for provider {provider} is unknown{stale}: no fresh "
                           f"cumulative observation for pool {view.get('pool')}")
        if view.get("denied"):
            reasons.append(f"capacity for provider {provider} is denied in pool "
                           f"{view.get('pool')}: a denial overrides dwell and burn plans")
    reasons.extend(_dwell_reasons(events, policy, views, policy_raw, now))
    return reasons


def plan_burn(events: list[dict], policy_raw: dict, now: datetime,
              ready: list[tuple[str, str]], caps: dict,
              running: int, unlanded: int) -> dict | None:
    """Plan a burn of expiring capacity, or return ``None``.

    ``ready`` is ``[(release_id, size)]`` in backlog order.  Nothing is planned
    while :func:`check` reports a reason.  A window then qualifies when it ends
    within ``burn.start_within_s`` and its measured burnable headroom (budget
    minus lane, outside-lane and in-flight spend) is at least
    ``burn.min_burnable``.  Items are taken in order while their summed policy
    estimate fits the burnable headroom and the plan stays within
    ``min(concurrency - running, accepted_unlanded_max - unlanded)``.
    """
    rules = _burn_rules(policy_raw)
    if rules is None:
        return None
    start_within_s, min_burnable = rules

    slots = _slots(caps, running, unlanded)
    if slots <= 0:
        return None

    now = _as_utc(now)

    try:
        policy = AllocationPolicy.from_dict(policy_raw)
    except PolicyError:
        return None
    if check(events, policy_raw, now):
        return None
    qualified_views = qualified(events, policy, now)

    for provider, spec in policy.providers.items():
        if not spec.expiring:
            continue
        provider_raw = policy_raw.get("providers", {}).get(provider, {})
        estimates = provider_raw.get("estimates", {})
        if not isinstance(estimates, dict):
            estimates = {}
        qview = qualified_views.get(provider) or {}
        outside = qview.get("outside_lane")
        lane_used = float(qview.get("lane_used") or 0.0)
        held = float(qview.get("in_flight") or 0.0)
        if outside is None:
            continue
        anchor = _observation_anchor(events, provider, spec)
        for window in spec.windows:
            _, end = _burn_window_bounds(now, window.anchor or anchor, window.length_s)
            remaining_s = (end - now).total_seconds()
            if remaining_s > start_within_s:
                continue
            measured = float(window.budget) - lane_used - float(outside) - held
            burnable = _tidy(max(0.0, measured))
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


def _new_decision_id() -> str:
    return f"dec-{uuid.uuid4().hex}"


def _record(log, data: dict) -> None:
    with log.locked():
        log.append("lane.decision", data)


def _revalidation_reasons(events: list[dict], policy_raw: dict, now: datetime,
                          proposal_id: str) -> list[str]:
    """``check`` over the log without this plan's own allocation records.

    Applying one item writes an ``applied`` allocation decision; that record
    must not dwell-block the remaining items of the same proposal, while a
    foreign applied decision still does.
    """
    foreign = [
        ev for ev in events
        if not (isinstance(ev, dict) and ev.get("type") == "lane.decision"
                and isinstance(ev.get("data"), dict)
                and (ev["data"].get("proposal_id") == proposal_id
                     or ev["data"].get("decision_id") == proposal_id))
    ]
    return check(foreign, policy_raw, now)


def execute_plan(log, plan: dict, policy_raw: dict, now: datetime, admit) -> list:
    """Record, revalidate and apply a burn plan item by item.

    The proposal is recorded before anything is admitted.  Each item re-runs
    :func:`check` against the current log and stops the plan when a refusal
    reason appears; the ``admit`` callback returns a claim (or a string reason
    it refused).  Applied items are correlated with their proposal and claim,
    and nothing is executed here: callers run the returned claims.
    """
    now = _as_utc(now)
    revision = _policy_revision(policy_raw)
    items = list(plan.get("items") or [])
    burnable = plan.get("burnable")
    snapshot_ts = format_ts(now)
    proposal_id = _new_decision_id()
    _record(log, {
        "decision_id": proposal_id,
        "kind": "allocation",
        "phase": "proposed",
        "chosen": f"{plan.get('provider')}/{plan.get('window')}",
        "mechanism": MECHANISM_BURN,
        "policy_revision": revision,
        "items": items,
        "burnable": burnable,
        "snapshot_ts": snapshot_ts,
    })
    claims: list = []
    for item_id in items:
        reasons = _revalidation_reasons(log.read(), policy_raw, now, proposal_id)
        if reasons:
            _record(log, {
                "decision_id": _new_decision_id(),
                "kind": "allocation",
                "phase": "refused",
                "chosen": None,
                "mechanism": MECHANISM_BURN,
                "policy_revision": revision,
                "proposal_id": proposal_id,
                "snapshot_ts": snapshot_ts,
                "reasons": list(reasons),
            })
            break
        outcome = admit(item_id)
        if isinstance(outcome, str):
            _record(log, {
                "decision_id": _new_decision_id(),
                "kind": "allocation",
                "phase": "refused",
                "chosen": None,
                "mechanism": MECHANISM_BURN,
                "policy_revision": revision,
                "proposal_id": proposal_id,
                "snapshot_ts": snapshot_ts,
                "reasons": [outcome],
            })
            break
        attempt_id = getattr(outcome, "attempt_id", None)
        _record(log, {
            "decision_id": _new_decision_id(),
            "kind": "allocation",
            "phase": "applied",
            "proposal_id": proposal_id,
            "chosen": item_id,
            "mechanism": MECHANISM_BURN,
            "policy_revision": revision,
            "subject": {"item_id": item_id, "attempt_id": attempt_id},
            "burnable": burnable,
            "snapshot_ts": snapshot_ts,
        })
        claims.append(outcome)
    return claims


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
    events = log.read()
    reasons = check(events, policy_raw, now)
    if reasons:
        print("no burn plan:")
        for reason in reasons:
            print(f"  - {reason}")
        return 0
    lane, repos = load_lane(args.lane), load_repos()
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
        claims = execute_plan(log, plan, policy_raw, now,
                              lambda rid: runner.admit(args.lane, log, only=rid))
        for claim in claims:
            print(f"claimed {claim.attempt_id} -> {claim.model}", flush=True)
            print(runner.execute(claim, log), flush=True)
        if not claims:
            print("no items applied")
    return 0
