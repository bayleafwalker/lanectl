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
            providers[str(name)] = ProviderPolicy(
                name=str(name), unit=unit, expiring=bool(spec.get("expiring", False)),
                windows=windows, reservations=reservations, estimates=estimates,
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


def capacity_admission(events: list[dict], policy: AllocationPolicy | None,
                       now: datetime, provider: str | None, size: str) -> dict:
    """Decide in shadow whether capacity would admit one attempt of ``size``.

    Static caps stay authoritative; this is a second opinion recorded alongside
    them.  The estimate is the policy's per-size placeholder until
    ``ESTIMATE_SAMPLE`` adapter-recorded attempts of that size exist, at which
    point their mean replaces it.  Burnable is the floor over the provider's
    windows (``project``): an estimate is admitted when it fits inside every
    window.  A missing policy, or a provider the policy does not name, admits
    with a reason rather than blocking on an unknown.
    """
    if policy is None:
        return {"decision": "admit", "estimate": None, "burnable": None,
                "reasons": ["no allocation policy; capacity does not gate admission"]}
    spec = policy.providers.get(provider) if provider is not None else None
    if spec is None:
        return {"decision": "admit", "estimate": None, "burnable": None,
                "reasons": [f"provider {provider!r} is not in the allocation policy; admitting"]}
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
    windows = project(events, policy, now).get(provider, {})
    burnable = _tidy(min((w["burnable"] for w in windows.values()), default=0.0))
    decision = "admit" if burnable >= estimate else "block"
    reasons.append(f"burnable {burnable} {'>=' if decision == 'admit' else '<'} estimate {estimate}")
    return {"decision": decision, "estimate": estimate, "burnable": burnable,
            "reasons": reasons}


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
    views = project(log.read(), policy, now)
    if args.json:
        print(json.dumps({"as_of": format_ts(now), "revision": policy.revision,
                          "providers": views}, indent=1, sort_keys=True))
        return 0
    print(f"as of {format_ts(now)} (allocation revision {policy.revision})")
    for provider, windows in views.items():
        for name, w in windows.items():
            burn = "allowed" if w["burn_down_allowed"] else "held"
            print(f"{provider:16} {name:8} {w['window_start']} .. {w['window_end']}  "
                  f"used={w['used']} remaining={w['remaining']} "
                  f"reserved={w['reserved_effective']} burnable={w['burnable']} ({burn})")
    return 0
