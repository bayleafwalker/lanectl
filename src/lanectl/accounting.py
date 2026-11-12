"""Lifecycle accounting with attribution and unknown costs.

``accounting_timeline`` is a pure projection over an append-only event stream.
It attributes usage to one requested item/attempt, prices only what the
matching published provider table can price, and reports everything else as
*unknown* rather than as zero.  Lifecycle phases (queued, execution,
integration, verification) are projected into second-by-second intervals that
each carry their source timestamps, log checkpoints and basis.

Nothing here writes, reads the network, or emits events.  Dollar figures are
estimates from published :mod:`lanectl.costs` prices, never money recorded in
the log.  Verification is a local receipt of confirmed closure, not an
independent owner fact.
"""
from __future__ import annotations

import json
import math

from .costs import _UNIT_COLUMNS, _in_peak, _load_policy_raw, _parse_ts
from .events import EventLog

#: ``usage.recorded`` source that is the operator rather than a lane worker.
_OPERATOR_SOURCE = "claude-code-interactive"

#: Every local interval is a projection over the append-only event log.
_SOURCE = "lanectl.events"

_PER_MILLION = 1_000_000.0

_PHASE_KINDS = ("queued", "execution", "integration", "verification")

#: unit -> price column (mirrors ``costs._UNIT_COLUMNS``).
_UNIT_COLUMN = dict(_UNIT_COLUMNS)


def _is_number(value) -> bool:
    """True for a finite real number; booleans are not measurements."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)))


def _duration(start_ev, end_ev) -> int | None:
    """Whole seconds between two events' timestamps, or ``None`` when unknown.

    A misordered pair (end before start) never becomes a negative duration, and
    an absent endpoint stays unknown rather than being extrapolated to now.
    """
    start = _parse_ts(start_ev.get("ts"))
    end = _parse_ts(end_ev.get("ts"))
    if start is None or end is None:
        return None
    seconds = (end - start).total_seconds()
    if seconds < 0:
        return None
    return int(round(seconds))


def _data(ev) -> dict:
    data = ev.get("data") if isinstance(ev, dict) else None
    return data if isinstance(data, dict) else {}


def _provider_prices(policy_raw, provider) -> dict | None:
    """The matching provider's price table, or ``None`` when absent.

    Only the provider named by the usage event is consulted: one provider's
    rates never price another provider's usage.
    """
    if not isinstance(policy_raw, dict):
        return None
    providers = policy_raw.get("providers")
    if not isinstance(providers, dict):
        return None
    entry = providers.get(provider)
    if not isinstance(entry, dict):
        return None
    prices = entry.get("prices")
    return prices if isinstance(prices, dict) else None


def _price_event(units, model, ts, prices) -> float | None:
    """USD for one usage event against one provider table, or ``None`` unpriced.

    An event is priced only when it reports at least one unit and *every*
    reported nonzero unit maps to a present, finite price column.  One priced
    column never proves the whole event priced: an unknown unit, a nonnumeric
    measurement, an empty units dict or a missing column all make the event
    unpriced rather than silently zero.
    """
    if not isinstance(units, dict) or not units:
        return None
    if not isinstance(prices, dict) or not isinstance(model, str) or not model:
        return None
    models = prices.get("models")
    entry = models.get(model) if isinstance(models, dict) else None
    if not isinstance(entry, dict):
        return None
    when = _parse_ts(ts)
    tier = entry.get("peak") if when is not None and _in_peak(when, prices) else None
    if not isinstance(tier, dict):
        tier = entry.get("offpeak") or {}
    if not isinstance(tier, dict):
        return None
    total = 0.0
    for unit, amount in units.items():
        if not _is_number(amount):
            return None                     # unmeasured / nonnumeric value
        value = float(amount)
        if value < 0:
            return None                     # a negative measurement is unknown
        if value == 0:
            continue                        # a measured zero needs no column
        column = _UNIT_COLUMN.get(unit)
        if column is None:
            return None                     # unknown unit
        rate = tier.get(column)
        if not _is_number(rate):
            return None                     # missing / invalid price column
        total += value / _PER_MILLION * float(rate)
    return total


def _empty_section() -> dict:
    return {
        "units": {},
        "usd_est": None,
        "known_usd_est": None,
        "priced_events": 0,
        "unpriced_events": 0,
        "events": 0,
        "estimate": True,
    }


def _add_usage(section, ev, data, policy_raw) -> None:
    """Fold one attributed usage record into its lane/operator section."""
    units = data.get("units")
    raw_units = units if isinstance(units, dict) else {}
    # Preserve raw reported units (including unknown or unmeasured values)
    # while summing every numeric measurement.
    for unit, amount in raw_units.items():
        if _is_number(amount):
            section["units"][unit] = section["units"].get(unit, 0) + amount
        else:
            section["units"][unit] = amount
    section["events"] += 1
    usd = _price_event(units, data.get("model"), ev.get("ts"),
                       _provider_prices(policy_raw, data.get("provider")))
    if usd is None:
        section["unpriced_events"] += 1
    else:
        section["priced_events"] += 1
        section["known_usd_est"] = (section["known_usd_est"] or 0.0) + usd


def _finalize_section(section) -> dict:
    """Set ``usd_est`` to the total only when every reported event is priced."""
    if section["events"] == 0 or section["unpriced_events"] > 0:
        section["usd_est"] = None
    else:
        section["usd_est"] = section["known_usd_est"]
    if section["priced_events"] == 0:
        section["known_usd_est"] = None
    return section


def _attributed(ev, item_id, attempt_id) -> bool:
    """Whether a usage record belongs to the requested item/attempt scope.

    Release-level usage (an item with no attempt) is attributed for a release
    query and excluded for an attempt query.
    """
    if ev.get("item_id") != item_id:
        return False
    if attempt_id is not None:
        if _data(ev).get("attempt_id") != attempt_id:
            return False
    return True


def _compute_usage(events, policy_raw, item_id, attempt_id):
    """Lane/operator usage sections plus attributed/unattributed counts.

    Unattributed usage is counted explicitly, never silently charged, and the
    projection never infers absent measurements as full attribution coverage.
    """
    sections = {"lane": _empty_section(), "operator": _empty_section()}
    attributed = 0
    unattributed = 0
    for ev in events:
        if not isinstance(ev, dict) or ev.get("type") != "usage.recorded":
            continue
        data = _data(ev)
        if _attributed(ev, item_id, attempt_id):
            attributed += 1
            name = "operator" if data.get("source") == _OPERATOR_SOURCE else "lane"
            _add_usage(sections[name], ev, data, policy_raw)
        else:
            unattributed += 1
    for section in sections.values():
        _finalize_section(section)
    return sections, attributed, unattributed


def _interval(kind, start, end, *, basis="event log checkpoints",
              attempt_id=None) -> dict:
    """One phase interval carrying its source, timestamps, checkpoints and basis."""
    start_n, start_ev = start or (None, None)
    end_n, end_ev = end or (None, None)
    seconds = None
    if start_ev is not None and end_ev is not None:
        seconds = _duration(start_ev, end_ev)
    return {
        "source": _SOURCE,
        "kind": kind,
        "basis": basis,
        "attempt_id": attempt_id,
        "start": start_ev.get("ts") if start_ev is not None else None,
        "end": end_ev.get("ts") if end_ev is not None else None,
        "start_checkpoint": start_n,
        "end_checkpoint": end_n,
        "seconds": seconds,
    }


def _phase(intervals) -> dict:
    """Aggregate a phase, keeping an unknown endpoint out of the total.

    ``seconds`` is the sum only when every contributing interval is known.  A
    partial subtotal is exposed separately as ``known_seconds`` and is never
    presented as the total.
    """
    values = [iv["seconds"] for iv in intervals]
    known = [value for value in values if value is not None]
    subtotal = sum(known) if known else None
    if not intervals or any(value is None for value in values):
        total = None
        basis = "unknown: contributing interval has a missing endpoint"
    else:
        total = sum(values)
        basis = "sum of interval seconds (all endpoints known)"
    return {"seconds": total, "known_seconds": subtotal, "basis": basis,
            "intervals": intervals}


def _is_item_event(ev, item_id) -> bool:
    if ev.get("item_id") == item_id:
        return True
    return (ev.get("type") == "release.published"
            and _data(ev).get("release_id") == item_id)


def _closure_for(landing, closers):
    """First explicit local receipt closing this landing's train, if any.

    A receipt must agree on ``train_id`` and report ``ok=true``.  Owner flags
    (``owner_reported``/``pending_owner``) never substitute for the explicit
    ``closed=true`` receipt.
    """
    train_id = _data(landing).get("train_id")
    if train_id is None:
        return None
    for numbered in closers:
        data = _data(numbered[1])
        if (data.get("train_id") == train_id and data.get("closed") is True
                and data.get("ok") is True):
            return numbered
    return None


def _compute_phases(events, item_id, attempt_id) -> dict:
    """Project queued/execution/integration/verification intervals.

    Execution is per attempt: each claim is joined to its own finish, never the
    first claim to the last finish across retries.  Gaps between a finished
    attempt and the next claim are labelled ``waiting`` and excluded from the
    execution total.  An attempt query never borrows another attempt's landing
    or verification interval.
    """
    published = None
    claims: list[tuple[int, dict]] = []
    seen_claims: set = set()
    finishes: dict = {}
    landings: list[tuple[int, dict]] = []
    seen_landings: set = set()
    closers: list[tuple[int, dict]] = []

    for n, ev in enumerate(events, 1):
        if not isinstance(ev, dict) or not _is_item_event(ev, item_id):
            continue
        kind = ev.get("type")
        data = _data(ev)
        if kind == "release.published" and published is None:
            published = (n, ev)
        elif kind == "item.claimed":
            aid = data.get("attempt_id")
            if aid not in seen_claims:
                seen_claims.add(aid)
                claims.append((n, ev))
        elif kind == "attempt.finished":
            finishes.setdefault(data.get("attempt_id"), (n, ev))
        elif kind == "item.landed":
            key = (data.get("attempt_id"), data.get("train_id"))
            if key not in seen_landings:
                seen_landings.add(key)
                landings.append((n, ev))
        elif kind == "work.synced":
            closers.append((n, ev))

    selected = claims
    if attempt_id is not None:
        selected = [(n, ev) for n, ev in claims
                    if _data(ev).get("attempt_id") == attempt_id]

    queued = []
    # Queueing is a release-level phase: the item's first claim, even when the
    # query selects one attempt.  Only landing/verification are attempt-scoped.
    if published is not None and claims:
        queued.append(_interval("queued", published, claims[0],
                                basis="release.published -> item.claimed"))

    execution = []
    waiting = []
    prev_finish = None
    for n, claim in selected:
        aid = _data(claim).get("attempt_id")
        finish = finishes.get(aid)
        if prev_finish is not None:
            waiting.append(_interval(
                "waiting", prev_finish, (n, claim), attempt_id=aid,
                basis="attempt.finished -> next item.claimed"))
        execution.append(_interval(
            "execution", (n, claim), finish, attempt_id=aid,
            basis="item.claimed -> attempt.finished"))
        prev_finish = finish

    integration = []
    verification = []
    for landing in landings:
        aid = _data(landing[1]).get("attempt_id")
        if attempt_id is not None and aid != attempt_id:
            continue
        integration.append(_interval(
            "integration", finishes.get(aid), landing, attempt_id=aid,
            basis="attempt.finished -> item.landed"))
        closure = _closure_for(landing[1], closers)
        verification.append(_interval(
            "verification", landing, closure, attempt_id=aid,
            basis="item.landed -> work.synced(closed=true, ok=true, same train_id)"))

    return {
        "queued": _phase(queued),
        "execution": {**_phase(execution), "waiting": _phase(waiting)},
        "integration": _phase(integration),
        "verification": _phase(verification),
    }


def _price_revision(policy_raw):
    if not isinstance(policy_raw, dict):
        return None
    return policy_raw.get("revision")


def accounting_timeline(events, policy_raw, *, item_id, attempt_id=None) -> dict:
    """Pure projection of lifecycle phases, usage, attribution and pricing.

    Returns ``item_id``, ``attempt_id``, ``phases``, ``usage``, ``attribution``
    and ``price_revision``.  No writes, new events, network or dependencies.
    """
    events = list(events or ())
    phases = _compute_phases(events, item_id, attempt_id)
    usage, attributed, unattributed = _compute_usage(events, policy_raw, item_id,
                                                     attempt_id)
    return {
        "item_id": item_id,
        "attempt_id": attempt_id,
        "phases": phases,
        "usage": usage,
        "attribution": {
            "attributed_events": attributed,
            "unattributed_events": unattributed,
        },
        "price_revision": _price_revision(policy_raw),
    }


def _fmt_seconds(value) -> str:
    return "unknown" if value is None else f"{value}s"


def _fmt_usd(value) -> str:
    return "unknown" if value is None else f"${value:.6f}"


def _fmt_units(units) -> str:
    return json.dumps(units or {}, sort_keys=True)


def render_timeline(result) -> str:
    """Plain-text timeline labelling estimates, revision, units and unknowns."""
    scope = f"item {result['item_id']}"
    if result.get("attempt_id"):
        scope += f" attempt {result['attempt_id']}"
    lines = [f"accounting {scope}"]
    rev = result.get("price_revision")
    lines.append(f"price revision: {rev if rev is not None else 'unknown'} "
                 "(estimate from published prices)")
    lines.append("phases:")
    for kind in _PHASE_KINDS:
        phase = result["phases"][kind]
        lines.append(f"  {kind}: {_fmt_seconds(phase['seconds'])} "
                     f"[{phase.get('basis', 'basis unknown')}]")
        if phase.get("known_seconds") is not None and phase.get("seconds") is None:
            lines.append(f"    known subtotal: {_fmt_seconds(phase['known_seconds'])} "
                         "(not a total)")
        if kind == "execution":
            waiting = phase.get("waiting") or {}
            lines.append(f"    waiting: {_fmt_seconds(waiting.get('seconds'))} "
                         "(separate from execution)")
        for iv in phase["intervals"]:
            lines.append(
                f"    - {iv['kind']}: {iv['start'] or 'unknown'} -> "
                f"{iv['end'] or 'unknown'} ({_fmt_seconds(iv['seconds'])}) "
                f"checkpoint {iv['start_checkpoint']}->{iv['end_checkpoint']} "
                f"[{iv.get('basis', 'basis unknown')}]")
    lines.append("usage (estimate; unknown is not zero):")
    for name in ("lane", "operator"):
        section = result["usage"][name]
        lines.append(
            f"  {name}: events={section['events']} "
            f"priced={section['priced_events']} unpriced={section['unpriced_events']} "
            f"estimate={section.get('estimate', True)} "
            f"usd_est={_fmt_usd(section['usd_est'])} "
            f"known_usd_est={_fmt_usd(section['known_usd_est'])}")
        lines.append(f"    units: {_fmt_units(section.get('units'))}")
    attribution = result["attribution"]
    total = attribution["attributed_events"] + attribution["unattributed_events"]
    coverage = "unknown" if total == 0 else f"{attribution['attributed_events']}/{total}"
    lines.append(
        f"attribution: attributed={attribution['attributed_events']} "
        f"unattributed={attribution['unattributed_events']} coverage={coverage}")
    return "\n".join(lines)


def register(sub) -> dict:
    p = sub.add_parser("accounting",
                       help="lifecycle accounting with attribution and unknown costs")
    p.add_argument("--item", required=True, help="release/item identifier to account for")
    p.add_argument("--attempt", help="restrict accounting to one attempt")
    p.add_argument("--json", action="store_true",
                   help="emit the accounting projection as JSON")
    return {"accounting": _cmd}


def _cmd(args, log: EventLog) -> int:
    events = log.read()                     # read() validates every record
    policy_raw = _load_policy_raw()
    result = accounting_timeline(events, policy_raw, item_id=args.item,
                                 attempt_id=args.attempt)
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(render_timeline(result))
    return 0
