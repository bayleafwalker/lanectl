"""OpenTelemetry span export for lane attempts and operator sessions.

``spans`` folds the append-only event log into an OTLP/JSON
``ExportTraceServiceRequest`` document, written by hand (no dependency) so a
collector's ``otlpjsonfile`` receiver can ingest it.  Two span kinds are
emitted:

* ``lane.attempt`` — one per ``item.claimed``, spanning the claim through the
  attempt's ``experiment.recorded`` (or the latest event that names the
  attempt), with usage tokens and a published-price dollar estimate.
* ``operator.session`` — one per ``usage.recorded`` whose ``source`` is
  ``claude-code-interactive`` and that carries an ``item_id``, with its own
  role and token counts.

Attribute values follow the OTLP/JSON ``AnyValue`` shape: ``stringValue`` for
strings, ``intValue`` as a *decimal string* (uint64-safe) and ``doubleValue``
for floats.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from . import costs
from .events import EventLog

_SERVICE_NAME = "lanectl"


def _nanos(ts) -> int:
    """Unix time in nanoseconds for an ISO-8601 timestamp, as an integer."""
    if not isinstance(ts, str) or not ts:
        return 0
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1_000_000_000)


def _num(value):
    """Numeric value or ``0`` for anything that is not a real number."""
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _string(value) -> dict:
    return {"stringValue": "" if value is None else str(value)}


def _int(value) -> dict:
    return {"intValue": str(int(value))}


def _double(value) -> dict:
    return {"doubleValue": float(value)}


def _attr(key: str, value: dict) -> dict:
    return {"key": key, "value": value}


def _hex(value, n: int) -> str:
    return hashlib.sha256(str(value).encode()).hexdigest()[:n]


def _tokens(usage_events) -> tuple[int, int]:
    """(input_tokens, output_tokens) summed over a list of usage events."""
    input_tokens = 0.0
    output_tokens = 0.0
    for ev in usage_events:
        data = ev.get("data")
        units = (data or {}).get("units") or {}
        input_tokens += _num(units.get("input_tokens"))
        output_tokens += _num(units.get("output_tokens"))
    return int(input_tokens), int(output_tokens)


def _attempt_cost(usage_events, policy_raw) -> float | None:
    """Dollar estimate over an attempt's usage, or ``None`` when unpriced."""
    tables = costs._price_tables(policy_raw)
    if not tables:
        return None
    total = 0.0
    priced = False
    for ev in usage_events:
        data = ev.get("data") or {}
        units = data.get("units")
        model = data.get("model")
        usd = None
        for prices in tables:
            usd = costs.price_usage(units, model, ev.get("ts"), prices)
            if usd is not None:
                break
        if usd is not None:
            total += usd
            priced = True
    return total if priced else None


def _attempt_span(claim, usage_events, experiment, latest_ns: int, cost) -> dict:
    item_id = claim.get("item_id")
    data = claim.get("data") or {}
    attempt_id = data.get("attempt_id")
    start_ns = _nanos(claim.get("ts"))
    end_ns = _nanos(experiment.get("ts")) if experiment is not None else latest_ns

    attrs = [
        _attr("lanectl.release_id", _string(item_id)),
        _attr("lanectl.attempt_id", _string(attempt_id)),
        _attr("gen_ai.request.model", _string(data.get("model"))),
    ]
    if experiment is not None:
        decision = (experiment.get("data") or {}).get("decision")
        if decision is not None:
            attrs.append(_attr("lanectl.decision", _string(decision)))
    input_tokens, output_tokens = _tokens(usage_events)
    attrs.append(_attr("gen_ai.usage.input_tokens", _int(input_tokens)))
    attrs.append(_attr("gen_ai.usage.output_tokens", _int(output_tokens)))
    if cost is not None:
        attrs.append(_attr("lanectl.cost_usd_est", _double(cost)))
    return {
        "name": "lane.attempt",
        "traceId": _hex(item_id, 32),
        "spanId": _hex(attempt_id, 16),
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(end_ns),
        "attributes": attrs,
    }


def _session_span(ev) -> dict:
    item_id = ev.get("item_id")
    data = ev.get("data") or {}
    session_id = data.get("session_id") or ""
    ts = ev.get("ts") or ""
    units = data.get("units") or {}
    ns = _nanos(ts)
    attrs = [
        _attr("lanectl.release_id", _string(item_id)),
        _attr("lanectl.role", _string(data.get("role") or "interactive")),
        _attr("gen_ai.request.model", _string(data.get("model"))),
        _attr("gen_ai.usage.input_tokens", _int(_num(units.get("input_tokens")))),
        _attr("gen_ai.usage.output_tokens", _int(_num(units.get("output_tokens")))),
    ]
    return {
        "name": "operator.session",
        "traceId": _hex(item_id, 32),
        "spanId": _hex(session_id + ts, 16),
        "startTimeUnixNano": str(ns),
        "endTimeUnixNano": str(ns),
        "attributes": attrs,
    }


def spans(events, policy_raw=None) -> dict:
    """Fold *events* into an OTLP/JSON ``ExportTraceServiceRequest`` dict."""
    claims: dict[str, dict] = {}
    experiments: dict[str, dict] = {}
    usage_by_attempt: dict[str, list[dict]] = {}
    latest_by_attempt: dict[str, int] = {}
    sessions: list[dict] = []

    for ev in events:
        if not isinstance(ev, dict):
            continue
        etype = ev.get("type")
        data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        if etype == "item.claimed":
            claims[data.get("attempt_id")] = ev
        elif etype == "experiment.recorded":
            experiments[data.get("attempt_id")] = ev
        elif etype == "usage.recorded":
            if data.get("source") == "claude-code-interactive" and ev.get("item_id"):
                sessions.append(_session_span(ev))
            if data.get("attempt_id"):
                usage_by_attempt.setdefault(data["attempt_id"], []).append(ev)
        # Track the latest event that names each attempt (the fallback end).
        if data.get("attempt_id"):
            ns = _nanos(ev.get("ts"))
            aid = data["attempt_id"]
            if ns > latest_by_attempt.get(aid, -1):
                latest_by_attempt[aid] = ns

    attempt_spans = []
    for attempt_id, claim in claims.items():
        usage = usage_by_attempt.get(attempt_id, [])
        attempt_spans.append(_attempt_span(
            claim,
            usage,
            experiments.get(attempt_id),
            latest_by_attempt.get(attempt_id, _nanos(claim.get("ts"))),
            _attempt_cost(usage, policy_raw),
        ))

    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [_attr("service.name", _string(_SERVICE_NAME))],
                },
                "scopeSpans": [
                    {
                        "scope": {"name": _SERVICE_NAME},
                        "spans": attempt_spans + sessions,
                    }
                ],
            }
        ]
    }


def register(sub) -> dict:
    p = sub.add_parser("otel", help="export the event log as OpenTelemetry spans")
    sp = p.add_subparsers(dest="otel_cmd", required=True, metavar="SUBCOMMAND")
    ex = sp.add_parser("export", help="write spans as one OTLP/JSON line")
    ex.add_argument("--out", metavar="PATH", required=True,
                    help="output file (one JSON document)")
    return {"otel": _cmd}


def _cmd(args, log: EventLog) -> int:
    events = log.read()
    doc = spans(events, costs._load_policy_raw())
    n = len(doc["resourceSpans"][0]["scopeSpans"][0]["spans"])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, separators=(",", ":")) + "\n")
    print(f"{n} spans -> {out}")
    return 0
