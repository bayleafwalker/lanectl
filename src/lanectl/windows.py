"""Detect provider window exhaustion from failed or escalated attempts.

No real exhaustion message has been logged yet, so the tail formats are
assumptions: matching stays tolerant (case-insensitive keywords, optional
punctuation) and only ever produces evidence, never a policy change. The
detections are ``window.observed`` payloads, which ``capacity.project`` already
uses to anchor a provider's fixed-length window on ``observed.reset_at``.

``lanectl windows`` prints detections; ``--record`` appends them. Attempts that
already have a recorded ``window.observed`` are skipped, so recording twice is
idempotent.
"""
from __future__ import annotations

import re
from datetime import timedelta

from .capacity import format_ts, parse_ts

WINDOW = "5h"

# A provider's quota or rate limit is exhausted: 429, "rate limit", "usage
# limit" or "quota", case-insensitive and tolerant of spacing.
_EXHAUSTED = re.compile(r"(429|rate\s*limit|usage\s*limit|quota)", re.IGNORECASE)

# "resets at <ISO>" with an optional clock time / offset, e.g.
# "resets at 2026-11-08T15:00:00Z" or "reset at 2026-11-08 15:00".
_RESET_AT = re.compile(
    r"reset(?:s|ting)?\s*(?:at|:)?\s*"
    r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)",
    re.IGNORECASE,
)

# "try again in N minutes|hours" / "retry after N seconds" (and near variants).
_RELATIVE = re.compile(
    r"(?:try\s+again|retry|reset(?:s)?)\s*(?:in|after)\s*"
    r"(\d+(?:\.\d+)?)\s*(second|minute|hour|sec|min|hr)s?\b",
    re.IGNORECASE,
)

_UNIT_S = {"sec": 1.0, "second": 1.0, "min": 60.0, "minute": 60.0,
           "hr": 3600.0, "hour": 3600.0}


def provider_for(model: object) -> str | None:
    """Map a claimed model to the provider whose window it consumes."""
    if not isinstance(model, str):
        return None
    if model.startswith("opencode-go/"):
        return "opencode"
    if model.startswith("claude-"):
        return "anthropic"
    return None


def reset_at(tail: str, exhausted_at: object) -> str | None:
    """Parse a reset timestamp from *tail*, relative to *exhausted_at* if needed."""
    absolute = _RESET_AT.search(tail)
    if absolute:
        parsed = parse_ts(absolute.group(1))
        if parsed is not None:
            return format_ts(parsed)
    relative = _RELATIVE.search(tail)
    if relative:
        start = parse_ts(exhausted_at)
        if start is not None:
            seconds = float(relative.group(1)) * _UNIT_S[relative.group(2).lower()]
            return format_ts(start + timedelta(seconds=seconds))
    return None


def detect(events: list[dict]) -> list[dict]:
    """Return ``window.observed`` payloads for exhausted attempts (pure)."""
    models: dict[str, object] = {}
    covered: set[str] = set()
    for ev in events:
        if not isinstance(ev, dict):
            continue
        kind, data = ev.get("type"), ev.get("data")
        if not isinstance(data, dict):
            continue
        if kind == "item.claimed":
            models[data.get("attempt_id")] = data.get("model")
        elif kind == "window.observed":
            observed = data.get("observed")
            if isinstance(observed, dict) and observed.get("attempt_id"):
                covered.add(str(observed["attempt_id"]))

    out: list[dict] = []
    for ev in events:
        if not isinstance(ev, dict) or ev.get("type") != "attempt.finished":
            continue
        data = ev.get("data")
        if not isinstance(data, dict):
            continue
        attempt_id = data.get("attempt_id")
        if not attempt_id or attempt_id in covered:
            continue
        if data.get("outcome") not in ("failed", "escalated"):
            continue
        tail = data.get("final_tail")
        if not isinstance(tail, str) or not _EXHAUSTED.search(tail):
            continue
        provider = provider_for(models.get(attempt_id))
        if provider is None:
            continue
        out.append({
            "provider": provider,
            "window": WINDOW,
            "observed": {
                "attempt_id": attempt_id,
                "exhausted_at": ev.get("ts"),
                "reset_at": reset_at(tail, ev.get("ts")),
            },
        })
    return out


def register(sub) -> dict:
    p = sub.add_parser("windows", help="detect provider window exhaustion from attempt failures")
    p.add_argument("--record", action="store_true",
                   help="append detections as window.observed events")
    return {"windows": _cmd}


def _cmd(args, log) -> int:
    detections = detect(log.read())
    for payload in detections:
        obs = payload["observed"]
        print(f"{payload['provider']:10} {payload['window']:4} {obs['attempt_id']:40} "
              f"exhausted_at={obs['exhausted_at']} reset_at={obs['reset_at']}")
        if args.record:
            log.append("window.observed", payload)
    if not detections:
        print("no provider exhaustion detected")
    return 0
