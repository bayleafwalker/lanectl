"""Capacity ledger and allocation projection.

Allocation policy describes, per provider, the unit capacity is measured in, the
fixed-length windows that budget it, and the share of each window reserved for
interactive work. ``project`` folds the append-only log into, for every provider
and window, the current window bounds, usage, remaining headroom and the part of
that headroom that may safely be burned down.

Window semantics
----------------
Windows are fixed length and aligned to an anchor: the policy window anchor, or
the ``reset_at`` of the latest ``window.observed`` for that provider and window.
A window boundary therefore lands on the anchor and repeats every ``length_s``.

Interactive reservations decay linearly toward the window end. The reserved pool
is ``reservation_fraction * budget``; interactive usage inside the window spends
from that pool first; whatever is left is scaled by the fraction of the window
still ahead. Expiring capacity above that decayed reservation is burnable.

``project`` is a pure function: it performs no I/O and depends only on its
arguments.  ``capacity_admission`` layers a shadow admission decision on the
projection: it estimates what an attempt of a given size would burn and admits
only when the provider's burnable floor covers it.
"""
from __future__ import annotations

import json
import math
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import home

# Anchor used when a window policy does not name one: the Unix epoch, so windows
# tile the UTC day deterministically (e.g. 5h windows start 00:00, 05:00, ...).
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class PolicyError(ValueError):
    """An allocation policy is structurally invalid."""


def parse_ts(value: object) -> datetime | None:
    """Parse an ISO-8601 timestamp (with ``Z``) into an aware UTC datetime."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_ts(dt: datetime) -> str:
    """Render an aware datetime as a UTC ``Z`` string."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _number(value: object, label: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PolicyError(f"{label} must be a number: {value!r}")
    return value


@dataclass(frozen=True)
class WindowPolicy:
    name: str
    length_s: int
    budget: int | float
    anchor: datetime | None = None


@dataclass(frozen=True)
class ProviderPolicy:
    name: str
    unit: str
    expiring: bool
    windows: tuple[WindowPolicy, ...]
    reservations: dict[str, float] = field(default_factory=dict)
    estimates: dict[str, int | float] = field(default_factory=dict)
    pool: str | None = None
    freshness_s: int | None = None
    # Whether the source named a pool or freshness deadline. Pre-qualification
    # policies (rev 4 and earlier, and tests that omit both) keep the legacy
    # ledger-only projection instead of treating every absence as unknown.
    qualified: bool = False

    def __post_init__(self) -> None:
        if not self.pool:
            object.__setattr__(self, "pool", f"{self.name}:default")


@dataclass(frozen=True)
class AllocationPolicy:
    """Parsed ``governance/allocation.toml``; the planner owns its numbers."""

    revision: int
    providers: dict[str, ProviderPolicy]

    @classmethod
    def from_dict(cls, raw: dict) -> "AllocationPolicy":
        if not isinstance(raw, dict):
            raise PolicyError("allocation policy must be a table")
        try:
            revision = int(raw.get("revision", 0))
            providers_raw = raw.get("providers", {})
        except (TypeError, ValueError) as exc:
            raise PolicyError(f"invalid allocation policy: {exc}") from exc
        if not isinstance(providers_raw, dict):
            raise PolicyError("providers must be a table")
        providers: dict[str, ProviderPolicy] = {}
        for name, spec in providers_raw.items():
            if not isinstance(spec, dict):
                raise PolicyError(f"provider {name!r} must be a table")
            windows_raw = spec.get("windows", ())
            if not isinstance(windows_raw, list):
                raise PolicyError(f"provider {name!r}: windows must be an array of tables")
            windows = tuple(_window(name, w) for w in windows_raw)
            unit = spec.get("unit")
            if not isinstance(unit, str) or not unit:
                raise PolicyError(f"provider {name!r}: unit must be a non-empty string")
            reservations_raw = spec.get("reservations", {})
            if not isinstance(reservations_raw, dict):
                raise PolicyError(f"provider {name!r}: reservations must be a table")
            reservations = {}
            for key, frac in reservations_raw.items():
                f = float(_number(frac, f"provider {name!r}: reservation {key!r}"))
                if not 0.0 <= f <= 1.0:
                    raise PolicyError(f"provider {name!r}: reservation {key!r} must be within [0, 1]")
                reservations[str(key)] = f
            estimates_raw = spec.get("estimates", {})
            if not isinstance(estimates_raw, dict):
                raise PolicyError(f"provider {name!r}: estimates must be a table")
            estimates = {str(size): _number(value, f"provider {name!r}: estimate {size!r}")
                         for size, value in estimates_raw.items()}
            pool_raw = spec.get("pool")
            if pool_raw is None:
                pool = f"{name}:default"
            elif not isinstance(pool_raw, str) or not pool_raw:
                raise PolicyError(f"provider {name!r}: pool must be a non-empty string")
            else:
                pool = pool_raw
            freshness = spec.get("freshness_s")
            if freshness is None:
                freshness_s = None
            else:
                seconds = _number(freshness, f"provider {name!r}: freshness_s")
                if not float(seconds).is_integer() or seconds < 0:
                    raise PolicyError(f"provider {name!r}: freshness_s must be non-negative whole seconds")
                freshness_s = int(seconds)
            providers[str(name)] = ProviderPolicy(
                name=str(name), unit=unit, expiring=bool(spec.get("expiring", False)),
                windows=windows, reservations=reservations, estimates=estimates,
                pool=pool, freshness_s=freshness_s,
                qualified="pool" in spec or "freshness_s" in spec,
            )
        return cls(revision=revision, providers=providers)

    @classmethod
    def load(cls, path: Path | str | None = None,
             root: Path | str | None = None) -> "AllocationPolicy | None":
        """Load a policy file, or return ``None`` when it is absent.

        ``root`` overrides the checkout root (default: ``LANECTL_HOME`` or this
        repository); the default path is ``governance/allocation.toml``.
        """
        target = Path(path) if path is not None else Path(root or home()) / "governance" / "allocation.toml"
        if not target.is_file():
            return None
        try:
            raw = tomllib.loads(target.read_text())
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise PolicyError(f"{target}: {exc}") from exc
        return cls.from_dict(raw)


def _window(provider: str, raw: object) -> WindowPolicy:
    if not isinstance(raw, dict):
        raise PolicyError(f"provider {provider!r}: window must be a table")
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise PolicyError(f"provider {provider!r}: window name must be a non-empty string")
    length = _number(raw.get("length_s"), f"provider {provider!r} window {name!r}: length_s")
    if not float(length).is_integer():
        raise PolicyError(f"provider {provider!r} window {name!r}: length_s must be whole seconds")
    length = int(length)
    if length <= 0:
        raise PolicyError(f"provider {provider!r} window {name!r}: length_s must be positive")
    budget = _number(raw.get("budget"), f"provider {provider!r} window {name!r}: budget")
    anchor = None
    if raw.get("anchor") is not None:
        anchor = parse_ts(raw.get("anchor"))
        if anchor is None:
            raise PolicyError(f"provider {provider!r} window {name!r}: bad anchor {raw.get('anchor')!r}")
    return WindowPolicy(name=name, length_s=length, budget=budget, anchor=anchor)


def _window_bounds(now: datetime, anchor: datetime | None, length_s: int) -> tuple[datetime, datetime]:
    """Return the fixed-length window containing ``now``."""
    base = anchor or EPOCH
    length = timedelta(seconds=length_s)
    index = math.floor((now - base).total_seconds() / length_s)
    start = base + length * index
    return start, start + length


def _matches(source: str, key: str) -> bool:
    """A reservation key names a usage source (``interactive`` matches
    ``claude-code-interactive``)."""
    if source == key:
        return True
    tokens = set(source.replace("_", "-").split("-"))
    return key.replace("_", "-") in tokens


def _observed_anchor(events: list[dict], provider: str, window: str,
                     fallback: datetime | None) -> datetime | None:
    """Latest ``window.observed`` reset_at for this provider/window, else fallback."""
    newest: tuple[datetime, datetime] | None = None
    for ev in events:
        if not isinstance(ev, dict) or ev.get("type") != "window.observed":
            continue
        data = ev.get("data")
        if not isinstance(data, dict):
            continue
        if data.get("provider") != provider or data.get("window") != window:
            continue
        observed = data.get("observed")
        if not isinstance(observed, dict):
            continue
        reset_at = parse_ts(observed.get("reset_at"))
        if reset_at is None:
            continue
        seen_at = parse_ts(ev.get("ts")) or reset_at
        if newest is None or seen_at >= newest[0]:
            newest = (seen_at, reset_at)
    return newest[1] if newest is not None else fallback


def _usage(events: list[dict], provider: str, unit: str) -> list[tuple[datetime, float, str]]:
    rows: list[tuple[datetime, float, str]] = []
    for ev in events:
        if not isinstance(ev, dict) or ev.get("type") != "usage.recorded":
            continue
        data = ev.get("data")
        if not isinstance(data, dict) or data.get("provider") != provider:
            continue
        ts = parse_ts(ev.get("ts"))
        units = data.get("units")
        if ts is None or not isinstance(units, dict):
            continue
        amount = units.get(unit)
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            continue
        rows.append((ts, float(amount), str(data.get("source", ""))))
    return rows


def project(events: list[dict], policy: AllocationPolicy, now: datetime) -> dict[str, dict[str, dict]]:
    """Fold the log into ``{provider: {window: view}}`` at ``now`` (pure)."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    out: dict[str, dict[str, dict]] = {}
    for provider, spec in policy.providers.items():
        rows = _usage(events, provider, spec.unit)
        views: dict[str, dict] = {}
        for window in spec.windows:
            anchor = _observed_anchor(events, provider, window.name, window.anchor)
            start, end = _window_bounds(now, anchor, window.length_s)
            used = 0.0
            reserved_used = 0.0
            for ts, amount, source in rows:
                if not start <= ts <= now:
                    continue
                used += amount
                if any(_matches(source, key) for key in spec.reservations):
                    reserved_used += amount
            remaining = window.budget - used
            reserved_pool = sum(frac * window.budget for frac in spec.reservations.values())
            time_left = max(0.0, min(1.0, (end - now).total_seconds() / window.length_s))
            reserved_effective = max(0.0, reserved_pool - reserved_used) * time_left
            burnable = max(0.0, remaining - reserved_effective) if spec.expiring else 0.0
            views[window.name] = {
                "window_start": format_ts(start),
                "window_end": format_ts(end),
                "used": _tidy(used),
                "remaining": _tidy(remaining),
                "reserved_effective": _tidy(reserved_effective),
                "burnable": _tidy(burnable),
                "burn_down_allowed": bool(spec.expiring and burnable > 0),
            }
        out[provider] = views
    return out


def _tidy(value: float) -> int | float:
    """Keep whole numbers integral in projections and JSON output."""
    return int(value) if float(value).is_integer() else value


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _capacity_rows(events: list[dict], provider: str, pool: str,
                   value_kind: str) -> list[tuple[datetime, datetime, dict]]:
    """``capacity.observed`` rows of one kind for a provider pool, oldest first."""
    rows: list[tuple[datetime, datetime, dict]] = []
    for ev in events:
        if not isinstance(ev, dict) or ev.get("type") != "capacity.observed":
            continue
        data = ev.get("data")
        if not isinstance(data, dict):
            continue
        if data.get("provider") != provider or data.get("pool") != pool:
            continue
        if data.get("value_kind") != value_kind:
            continue
        observed_at = parse_ts(data.get("observed_at")) or parse_ts(ev.get("ts"))
        if observed_at is None:
            continue
        seen_at = parse_ts(ev.get("ts")) or observed_at
        rows.append((observed_at, seen_at, data))
    rows.sort(key=lambda row: (row[0], row[1]))
    return rows


def _summed_usage(events: list[dict], provider: str, unit: str,
                  start: datetime, end: datetime) -> float:
    """Ledger usage for a provider/unit with ``start <= ts <= end``."""
    return sum(amount for ts, amount, _ in _usage(events, provider, unit)
               if start <= ts <= end)


def _denied(events: list[dict], provider: str, spec: ProviderPolicy,
            now: datetime) -> bool:
    """A denial observed in a current window that has not reset yet."""
    bounds = []
    for window in spec.windows:
        anchor = _observed_anchor(events, provider, window.name, window.anchor)
        bounds.append(_window_bounds(now, anchor, window.length_s))
    if not bounds:
        return False
    for observed_at, _, data in _capacity_rows(events, provider, spec.pool, "denial"):
        if not any(start <= observed_at < end for start, end in bounds):
            continue
        reset = parse_ts(data.get("reset_at"))
        if reset is None or reset > now:
            return True
    return False


def qualified(events: list[dict], policy: AllocationPolicy,
              now: datetime) -> dict[str, dict]:
    """Qualify each provider's capacity by pool, source and freshness.

    A cumulative host-wide snapshot only measures outside-lane spend while it is
    fresh. Missing or stale evidence is ``unknown``: it never collapses to zero
    usage or free capacity. A denial blocks its pool until the recorded reset.
    """
    now = _as_utc(now)
    projected = project(events, policy, now)
    out: dict[str, dict] = {}
    for provider, spec in policy.providers.items():
        pool = spec.pool or f"{provider}:default"
        windows = projected.get(provider, {})
        lane_used = _tidy(max((w["used"] for w in windows.values()), default=0.0))
        rows = _capacity_rows(events, provider, pool, "cumulative")
        observed_at: datetime | None = rows[-1][0] if rows else None
        basis = "unknown"
        stale = False
        outside_lane: int | float | None = None
        if rows:
            data = rows[-1][2]
            value = data.get("value")
            window_start = parse_ts(data.get("window_start"))
            if spec.freshness_s is not None:
                stale = now > observed_at + timedelta(seconds=spec.freshness_s)
            if (isinstance(value, (int, float)) and not isinstance(value, bool)
                    and window_start is not None and not stale):
                inside = _summed_usage(events, provider, spec.unit,
                                       window_start, observed_at)
                outside_lane = _tidy(max(0.0, float(value) - inside))
                basis = "measured"
        out[provider] = {
            "pool": pool,
            "basis": basis,
            "observed_at": format_ts(observed_at) if observed_at is not None else None,
            "stale": stale,
            "lane_used": lane_used,
            "outside_lane": outside_lane,
            "denied": _denied(events, provider, spec, now),
        }
    return out


#: Observed attempts of a size needed before their mean replaces the policy estimate.
ESTIMATE_SAMPLE = 3


def _observed_estimate(events: list[dict], provider: str, unit: str,
                       size: str) -> float | None:
    """Mean adapter-recorded ``unit`` per attempt of ``size``, or None below the floor.

    Attempts are the ``experiment.recorded`` rows for this size, keyed by
    ``attempt_id``; their cost is the ``usage.recorded`` rows from the adapter
    for this provider, summed per attempt so a retry's multiple usage records
    count once.
    """
    attempts: set[str] = set()
    for ev in events:
        if not isinstance(ev, dict) or ev.get("type") != "experiment.recorded":
            continue
        data = ev.get("data")
        if not isinstance(data, dict) or data.get("size") != size:
            continue
        attempt_id = data.get("attempt_id")
        if isinstance(attempt_id, str) and attempt_id:
            attempts.add(attempt_id)
    if not attempts:
        return None
    totals: dict[str, float] = {}
    for ev in events:
        if not isinstance(ev, dict) or ev.get("type") != "usage.recorded":
            continue
        data = ev.get("data")
        if not isinstance(data, dict) or data.get("provider") != provider:
            continue
        if data.get("source") != "adapter":
            continue
        attempt_id = data.get("attempt_id")
        if attempt_id not in attempts:
            continue
        units = data.get("units")
        if not isinstance(units, dict):
            continue
        amount = units.get(unit)
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            continue
        totals[attempt_id] = totals.get(attempt_id, 0.0) + float(amount)
    if len(totals) < ESTIMATE_SAMPLE:
        return None
    return sum(totals.values()) / len(totals)


def _estimate(events: list[dict], spec: ProviderPolicy, provider: str,
              size: str) -> tuple[int | float, list[str]]:
    reasons: list[str] = []
    observed = _observed_estimate(events, provider, spec.unit, size)
    if observed is not None:
        estimate = _tidy(observed)
        reasons.append(f"estimate {estimate} is the mean of {ESTIMATE_SAMPLE}+ observed "
                       f"attempts of size {size}")
    elif size in spec.estimates:
        estimate = _tidy(float(spec.estimates[size]))
        reasons.append(f"estimate {estimate} is the policy estimate for size {size}")
    else:
        estimate = 0
        reasons.append(f"no estimate for size {size!r}; assuming 0")
    return estimate, reasons


def capacity_admission(events: list[dict], policy: AllocationPolicy | None,
                       now: datetime, provider: str | None, size: str) -> dict:
    """Decide in shadow whether capacity would admit one attempt of ``size``.

    Static caps stay authoritative; this is a second opinion recorded alongside
    them.  The estimate is the policy's per-size placeholder until
    ``ESTIMATE_SAMPLE`` adapter-recorded attempts of that size exist, at which
    point their mean replaces it.

    When a provider names a shared pool or freshness deadline, the decision is
    source-qualified: a denial blocks until reset; missing or stale evidence is
    unknown and the static policy decides (with no burnable figure); fresh
    cumulative evidence measures outside-lane spend, which is subtracted from
    every current window.  Pre-qualification policies keep the ledger-only
    projection.  A missing policy, or a provider the policy does not name,
    admits with a reason rather than blocking on an unknown.
    """
    if policy is None:
        return {"decision": "admit", "estimate": None, "burnable": None, "basis": "unknown",
                "reasons": ["no allocation policy; capacity does not gate admission"]}
    spec = policy.providers.get(provider) if provider is not None else None
    if spec is None:
        return {"decision": "admit", "estimate": None, "burnable": None, "basis": "unknown",
                "reasons": [f"provider {provider!r} is not in the allocation policy; admitting"]}
    estimate, reasons = _estimate(events, spec, provider, size)
    if not spec.qualified:
        windows = project(events, policy, now).get(provider, {})
        burnable = _tidy(min((w["burnable"] for w in windows.values()), default=0.0))
        decision = "admit" if burnable >= estimate else "block"
        reasons.append(f"burnable {burnable} {'>=' if decision == 'admit' else '<'} "
                       f"estimate {estimate}")
        return {"decision": decision, "estimate": estimate, "burnable": burnable,
                "basis": "measured", "reasons": reasons}

    view = qualified(events, policy, now)[provider]
    if view["denied"]:
        reasons.append(f"capacity denial for pool {view['pool']}; blocking until reset")
        return {"decision": "block", "estimate": estimate, "burnable": 0,
                "basis": "measured", "reasons": reasons}
    if view["basis"] == "unknown":
        stale = " (stale observation)" if view["stale"] else ""
        reasons.append(f"capacity unknown{stale}: no fresh cumulative observation for pool "
                       f"{view['pool']}; the static policy decides and no capacity is assumed free")
        return {"decision": "admit", "estimate": estimate, "burnable": None,
                "basis": "unknown", "reasons": reasons}

    outside = view["outside_lane"]
    windows = project(events, policy, now).get(provider, {})
    budgets = {window.name: window.budget for window in spec.windows}
    floor = min((budgets.get(name, 0) - w["used"] - outside - w["reserved_effective"])
                for name, w in windows.items()) if windows else 0.0
    burnable = _tidy(max(0.0, floor))
    decision = "admit" if burnable >= estimate else "block"
    reasons.append(f"burnable {burnable} {'>=' if decision == 'admit' else '<'} "
                   f"estimate {estimate} (outside-lane {outside} in pool {view['pool']})")
    return {"decision": decision, "estimate": estimate, "burnable": burnable,
            "basis": "measured", "reasons": reasons}


def shadow_admission(events: list[dict]) -> dict:
    """Aggregate ``admission.shadow`` events: recorded, agreed and agreement."""
    recorded = agreed = 0
    for ev in events:
        if not isinstance(ev, dict) or ev.get("type") != "admission.shadow":
            continue
        recorded += 1
        if (ev.get("data") or {}).get("agree"):
            agreed += 1
    return {"recorded": recorded, "agreed": agreed,
            "agreement": round(agreed / recorded, 3) if recorded else None}


def _fmt_shadow_admission(value: dict) -> list[str]:
    agreement = value.get("agreement")
    rendered = "-" if agreement is None else f"{agreement:.3f}"
    return ["", f"shadow_admission: recorded={value.get('recorded', 0)} "
                f"agreed={value.get('agreed', 0)} agreement={rendered}"]


def report_section():
    """Report section: shadow admission agreement."""
    return "shadow_admission", shadow_admission, _fmt_shadow_admission


def register(sub) -> dict:
    p = sub.add_parser("capacity", help="project capacity headroom and burnable allocation")
    p.add_argument("--json", action="store_true", help="emit the projection as JSON")
    return {"capacity": _cmd}


def _cmd(args, log) -> int:
    policy = AllocationPolicy.load()
    if policy is None:
        print("no allocation policy (governance/allocation.toml); nothing to project")
        return 0
    now = datetime.now(timezone.utc)
    events = log.read()
    views = project(events, policy, now)
    qualified_views = qualified(events, policy, now)
    if args.json:
        print(json.dumps({"as_of": format_ts(now), "revision": policy.revision,
                          "providers": views, "qualified": qualified_views},
                         indent=1, sort_keys=True))
        return 0
    print(f"as of {format_ts(now)} (allocation revision {policy.revision})")
    for provider, view in qualified_views.items():
        observed = view["observed_at"] or "-"
        outside = "-" if view["outside_lane"] is None else view["outside_lane"]
        stale = " stale" if view["stale"] else ""
        denied = " denied" if view["denied"] else ""
        print(f"{provider:16} pool={view['pool']} basis={view['basis']}{stale}{denied} "
              f"observed_at={observed} outside_lane={outside}")
    for provider, windows in views.items():
        for name, w in windows.items():
            burn = "allowed" if w["burn_down_allowed"] else "held"
            print(f"{provider:16} {name:8} {w['window_start']} .. {w['window_end']}  "
                  f"used={w['used']} remaining={w['remaining']} "
                  f"reserved={w['reserved_effective']} burnable={w['burnable']} ({burn})")
    return 0
