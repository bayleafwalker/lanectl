"""Probe provider-wide usage and compare it with what the ledger records.

Lane attempts record ``usage.recorded`` per attempt, but the provider's capacity
is also spent by interactive and ad-hoc work outside lanes. ``opencode stats``
reports the provider's own view of a window (default: the current day). The probe
turns that report into a ``window.observed`` payload and ``drift`` compares its
output tokens with the ledger rows inside the same range; the difference is the
usage the lanes never saw.

``lanectl probe opencode [--record]`` runs the real command and prints the
payload and the drift. ``--record`` appends the observed window to the log so
later runs compare against the latest probe.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone

from .capacity import AllocationPolicy, PolicyError, format_ts, parse_ts

PROVIDER = "opencode"
WINDOW = "day"
SOURCE = "opencode-stats"
TIMEOUT_S = 60


def _ms_to_iso(ms: object) -> str:
    """Render an epoch-millisecond instant as an ISO UTC ``...Z`` string."""
    if isinstance(ms, bool) or not isinstance(ms, (int, float)):
        raise ValueError(f"bad epoch-millisecond range bound: {ms!r}")
    return format_ts(datetime.fromtimestamp(ms / 1000, timezone.utc))


def _int(value: object) -> int:
    """Counters may be absent in older stats payloads; treat those as zero."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def probe_opencode(run) -> dict:
    """Run ``opencode stats`` through *run* and return a ``window.observed`` payload."""
    raw = run(["opencode", "stats", "--days", "0", "--json"])
    stats = json.loads(raw)
    if not isinstance(stats, dict):
        raise ValueError("opencode stats returned a non-object payload")
    rng = stats.get("range")
    if not isinstance(rng, dict):
        raise ValueError("opencode stats payload has no range")
    tokens = stats.get("tokens") if isinstance(stats.get("tokens"), dict) else {}
    cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
    return {
        "provider": PROVIDER,
        "window": WINDOW,
        "observed": {
            "source": SOURCE,
            "range_from": _ms_to_iso(rng.get("from")),
            "range_to": _ms_to_iso(rng.get("to")),
            "output_tokens": _int(tokens.get("output")),
            "input_tokens": _int(tokens.get("input")),
            "reasoning_tokens": _int(tokens.get("reasoning")),
            "cache_read_tokens": _int(cache.get("read")),
            "sessions": _int(stats.get("sessions")),
        },
    }


def capacity_observation(payload: dict, policy: AllocationPolicy | None) -> dict:
    """Turn a probe payload into a source-qualified ``capacity.observed`` row.

    OpenCode stats are cumulative for this host, not just the lanes: the row is
    marked ``scope = "host"`` so ``capacity.qualified`` can subtract the ledger
    and treat the remainder as outside-lane spend.
    """
    provider = str(payload.get("provider") or PROVIDER)
    observed = payload.get("observed") if isinstance(payload.get("observed"), dict) else {}
    spec = policy.providers.get(provider) if policy is not None else None
    pool = spec.pool if spec is not None and spec.pool else f"{provider}:default"
    observed_at = observed.get("range_to")
    row = {
        "provider": provider,
        "pool": pool,
        "source": SOURCE,
        "unit": "output_tokens",
        "basis": "measured",
        "observed_at": observed_at,
        "value": _int(observed.get("output_tokens")),
        "value_kind": "cumulative",
        "window_start": observed.get("range_from"),
        "scope": "host",
    }
    if spec is not None and spec.freshness_s is not None:
        start = parse_ts(observed_at)
        if start is not None:
            row["fresh_until"] = format_ts(start + timedelta(seconds=spec.freshness_s))
    return row


def _latest_probe(events: list[dict]) -> dict | None:
    """The most recently observed OpenCode stats window, or ``None``."""
    newest: tuple[datetime, dict] | None = None
    for ev in events:
        if not isinstance(ev, dict) or ev.get("type") != "window.observed":
            continue
        data = ev.get("data")
        if not isinstance(data, dict) or data.get("provider") != PROVIDER:
            continue
        observed = data.get("observed")
        if not isinstance(observed, dict) or observed.get("source") != SOURCE:
            continue
        if parse_ts(observed.get("range_from")) is None or parse_ts(observed.get("range_to")) is None:
            continue
        seen = parse_ts(ev.get("ts")) or datetime.min.replace(tzinfo=timezone.utc)
        if newest is None or seen >= newest[0]:
            newest = (seen, observed)
    return newest[1] if newest is not None else None


def drift(events: list[dict]) -> dict | None:
    """Compare the latest probe's output tokens with the ledger inside its range.

    Returns ``{"probe", "ledger", "unrecorded", "range_from", "range_to"}`` where
    ``unrecorded`` is provider-wide usage the ledger never recorded, or ``None``
    when no OpenCode probe has been observed yet.
    """
    observed = _latest_probe(events)
    if observed is None:
        return None
    start = parse_ts(observed["range_from"])
    end = parse_ts(observed["range_to"])
    ledger = 0
    for ev in events:
        if not isinstance(ev, dict) or ev.get("type") != "usage.recorded":
            continue
        data = ev.get("data")
        if not isinstance(data, dict) or data.get("provider") != PROVIDER:
            continue
        ts = parse_ts(ev.get("ts"))
        units = data.get("units")
        if ts is None or not isinstance(units, dict) or not start <= ts <= end:
            continue
        amount = units.get("output_tokens")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            continue
        ledger += int(amount)
    probe = _int(observed.get("output_tokens"))
    return {
        "probe": probe,
        "ledger": ledger,
        "unrecorded": probe - ledger,
        "range_from": observed["range_from"],
        "range_to": observed["range_to"],
    }


def register(sub) -> dict:
    p = sub.add_parser("probe", help="compare provider-wide usage with the ledger")
    p.add_argument("target", choices=[PROVIDER], help="provider to probe")
    p.add_argument("--record", action="store_true",
                   help="append the observed window to the event log")
    return {"probe": _cmd}


def _real_run(argv: list[str]) -> str:
    return subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT_S,
                          check=True).stdout


def _cmd(args, log) -> int:
    try:
        payload = probe_opencode(_real_run)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        print(f"probe {args.target}: {exc}")
        return 1
    print(json.dumps(payload, indent=1, sort_keys=True))
    if args.record:
        try:
            policy = AllocationPolicy.load()
        except PolicyError:
            policy = None
        with log.locked():
            ev = log.append("window.observed", payload)
            observed = log.append("capacity.observed", capacity_observation(payload, policy))
        print(f"recorded window.observed at {ev['ts']} and capacity.observed at {observed['ts']}")
    result = drift(log.read())
    if result is None:
        print("no probe in the log; nothing to compare")
    else:
        print(json.dumps(result, indent=1, sort_keys=True))
    return 0
