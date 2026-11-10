"""Dollar estimates from published prices.

Providers report ``cost_usd=0.0`` when a subscription bills a flat fee, so the
event log carries no money; published price tables are the honest bridge.  Peak
hours and weekdays select the tier, and unpriced usage is counted, never guessed.
"""
from __future__ import annotations

import tomllib
from datetime import datetime, timezone

from . import config

#: Unit -> price-column.  Other units are ignored on purpose: a price table
#: prices tokens, not steps or already-reported dollars.
_UNIT_COLUMNS = (
    ("input_tokens", "input"),
    ("output_tokens", "output"),
    ("reasoning_tokens", "output"),          # listed with no separate price
    ("cache_read_tokens", "cache_read"),
    ("cache_write_tokens", "cache_write"),
)

_PER_MILLION = 1_000_000.0


def _parse_ts(ts) -> datetime | None:
    """Parse an ISO-8601 timestamp into an aware UTC datetime, or ``None``."""
    if not isinstance(ts, str) or not ts:
        return None
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _in_peak(when: datetime, prices: dict) -> bool:
    """True when ``when`` falls on a peak weekday and in a peak hour range."""
    weekdays = prices.get("peak_weekdays") or []
    if when.weekday() not in weekdays:
        return False
    hour = when.hour
    for slot in prices.get("peak_hours_utc") or []:
        if not isinstance(slot, (list, tuple)) or len(slot) != 2:
            continue
        start, end = slot
        if start <= end:
            if start <= hour < end:
                return True
        elif hour >= start or hour < end:     # range wraps past midnight
            return True
    return False


def _number(value) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return 0.0


def price_usage(units: dict, model: str | None, ts: str | None, prices: dict) -> float | None:
    """USD for one ``usage.recorded`` units dict, or ``None`` when unpriced."""
    models = (prices or {}).get("models") or {}
    entry = models.get(model)
    if not isinstance(entry, dict):
        return None
    when = _parse_ts(ts)
    tier = entry.get("peak") if when is not None and _in_peak(when, prices) else None
    if not isinstance(tier, dict):
        tier = entry.get("offpeak") or {}
    if not isinstance(tier, dict) or not isinstance(units, dict):
        return 0.0
    total = 0.0
    for unit, column in _UNIT_COLUMNS:
        rate = tier.get(column)
        if isinstance(rate, (int, float)) and not isinstance(rate, bool):
            total += _number(units.get(unit)) / _PER_MILLION * rate
    return total


def _price_tables(policy_raw: dict) -> list[dict]:
    providers = (policy_raw or {}).get("providers") or {}
    return [p["prices"] for p in providers.values()
            if isinstance(p, dict) and isinstance(p.get("prices"), dict)]


def cost_summary(events: list[dict], policy_raw: dict) -> dict:
    """Per-model dollar estimate over settled usage, plus the unpriced count."""
    tables = _price_tables(policy_raw)
    summary: dict[str, dict] = {}
    unpriced = 0
    for ev in events:
        if not isinstance(ev, dict) or ev.get("type") != "usage.recorded":
            continue
        data = ev.get("data")
        if not isinstance(data, dict):
            continue
        model = data.get("model")
        if not isinstance(model, str) or not model:
            continue
        usd = None
        for prices in tables:
            usd = price_usage(data.get("units") or {}, model, ev.get("ts"), prices)
            if usd is not None:
                break
        if usd is None:
            unpriced += 1
            continue
        row = summary.setdefault(model, {"usd_est": 0.0, "events": 0})
        row["usd_est"] += usd
        row["events"] += 1
    return {**summary, "_unpriced": {"events": unpriced}}


def _load_policy_raw() -> dict:
    path = config.home() / "governance" / "allocation.toml"
    try:
        return tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def cost_usd(events: list[dict]) -> dict | None:
    """Report value: the summary, or ``None`` when governance publishes no prices."""
    policy_raw = _load_policy_raw()
    if not _price_tables(policy_raw):
        return None
    return cost_summary(events, policy_raw)


def _fmt_cost_usd(summary: dict | None) -> list[str]:
    lines = ["", "cost_usd (estimate from published prices):"]
    if summary is None:
        lines.append("  no price table")
        return lines
    for model in sorted(m for m in summary if not m.startswith("_")):
        row = summary[model]
        lines.append(f"  {model}: usd={row['usd_est']:.2f} events={row['events']}")
    unpriced = (summary.get("_unpriced") or {}).get("events", 0)
    lines.append(f"  unpriced usage events={unpriced}")
    return lines


def report_section():
    """Report section: dollar estimates from published prices."""
    return "cost_usd", cost_usd, _fmt_cost_usd
