"""Acceptance: OTLP/JSON export (planner-owned)."""
import hashlib
import json

import pytest

from lanectl import cli
from lanectl.contracts import make_event
from lanectl.otel import spans

L, C = "opencode-go/deepseek-v4.1-flash", "claude-opus-5-5"
PRICES = {"peak_hours_utc": [], "peak_weekdays": [],
          "models": {L: {"offpeak": {"input": 1.0, "output": 2.0}}}}
POLICY = {"revision": 1, "providers": {"opencode": {"unit": "output_tokens", "prices": PRICES}}}
CLAIM = {"lane": "implement", "model": L, "worker": "opencode", "attempt_id": "aa-a1"}


def _h(s, n):
    return hashlib.sha256(s.encode()).hexdigest()[:n]


def _events():
    return [
        make_event("item.claimed", CLAIM, item_id="aa", ts="2026-11-07T12:00:00Z"),
        make_event("usage.recorded", {"provider": "opencode", "source": "adapter", "model": L,
                                      "attempt_id": "aa-a1",
                                      "units": {"input_tokens": 1000, "output_tokens": 500}},
                   item_id="aa", ts="2026-11-07T12:01:00Z"),
        make_event("experiment.recorded", {"attempt_id": "aa-a1", "decision": "candidate",
                                           "model": L, "task_class": "glue", "size": "S",
                                           "worker": "opencode", "elapsed_s": 60.0,
                                           "gates_failed": [], "lane_revision": 3,
                                           "rules_revision": "r"},
                   item_id="aa", ts="2026-11-07T12:02:00Z"),
        make_event("usage.recorded", {"provider": "anthropic", "source": "claude-code-interactive",
                                      "session_id": "s1", "model": C, "role": "integrator",
                                      "units": {"input_tokens": 7, "output_tokens": 9}},
                   item_id="aa", ts="2026-11-07T12:05:00Z"),
        make_event("usage.recorded", {"provider": "anthropic", "source": "claude-code-interactive",
                                      "session_id": "s2", "model": C,
                                      "units": {"output_tokens": 1}}, ts="2026-11-07T12:06:00Z"),
    ]


def _attrs(span):
    out = {}
    for a in span["attributes"]:
        (kind, value), = a["value"].items()
        out[a["key"]] = int(value) if kind == "intValue" else value
    return out


def _all(doc):
    (rs,) = doc["resourceSpans"]
    assert {"key": "service.name", "value": {"stringValue": "lanectl"}} in rs["resource"]["attributes"]
    (ss,) = rs["scopeSpans"]
    return ss["spans"]


def test_attempt_span():
    (attempt,) = [s for s in _all(spans(_events(), POLICY)) if s["name"] == "lane.attempt"]
    assert attempt["traceId"] == _h("aa", 32) and attempt["spanId"] == _h("aa-a1", 16)
    assert attempt["startTimeUnixNano"] == str(1794052800 * 10**9)
    assert attempt["endTimeUnixNano"] == str((1794052800 + 120) * 10**9)
    a = _attrs(attempt)
    assert a["lanectl.release_id"] == "aa" and a["lanectl.attempt_id"] == "aa-a1"
    assert a["gen_ai.request.model"] == L and a["lanectl.decision"] == "candidate"
    assert a["gen_ai.usage.input_tokens"] == 1000 and a["gen_ai.usage.output_tokens"] == 500
    assert a["lanectl.cost_usd_est"] == pytest.approx(0.002)


def test_operator_session_span_only_for_attributed_usage():
    ops = [s for s in _all(spans(_events(), POLICY)) if s["name"] == "operator.session"]
    (op,) = ops
    assert op["traceId"] == _h("aa", 32)
    assert op["startTimeUnixNano"] == op["endTimeUnixNano"] == str((1794052800 + 300) * 10**9)
    a = _attrs(op)
    assert a["lanectl.role"] == "integrator" and a["gen_ai.usage.output_tokens"] == 9


def test_unpriced_attempt_omits_cost():
    (attempt,) = [s for s in _all(spans(_events(), {"revision": 1, "providers": {}}))
                  if s["name"] == "lane.attempt"]
    assert "lanectl.cost_usd_est" not in _attrs(attempt)


def test_cli_export_writes_one_json_document(estate, tmp_path, capsys):
    log = estate[2]
    for ev in _events():
        log.append(ev["type"], ev["data"], item_id=ev["item_id"])
    out = tmp_path / "spans.json"
    assert cli.main(["otel", "export", "--out", str(out)]) == 0
    doc = json.loads(out.read_text())
    assert len(_all(doc)) == 2
    assert f"2 spans -> {out}" in capsys.readouterr().out
