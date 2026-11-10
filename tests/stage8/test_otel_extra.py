"""Extra coverage for the OTLP/JSON span export (lanectl.otel)."""
import hashlib

from lanectl.contracts import make_event
from lanectl.otel import spans

L = "opencode-go/deepseek-v4.1-flash"
C = "claude-opus-5-5"


def _h(s, n):
    return hashlib.sha256(s.encode()).hexdigest()[:n]


def _all(doc):
    (rs,) = doc["resourceSpans"]
    (ss,) = rs["scopeSpans"]
    return ss["spans"]


def _attrs(span):
    out = {}
    for a in span["attributes"]:
        (kind, value), = a["value"].items()
        out[a["key"]] = int(value) if kind == "intValue" else value
    return out


def _claim(item_id="aa", attempt_id="aa-a1", ts="2026-11-07T12:00:00Z", model=L):
    return make_event("item.claimed", {"lane": "implement", "model": model,
                                       "worker": "opencode", "attempt_id": attempt_id},
                      item_id=item_id, ts=ts)


def _usage(units, *, attempt_id="aa-a1", item_id="aa", ts="2026-11-07T12:01:00Z",
           source="adapter", model=L, **extra):
    return make_event("usage.recorded", {"provider": "opencode", "source": source,
                                         "model": model, "attempt_id": attempt_id,
                                         "units": units, **extra},
                      item_id=item_id, ts=ts)


def test_int_values_are_decimal_strings():
    ev = [_claim(), _usage({"input_tokens": 3, "output_tokens": 4})]
    (span,) = [s for s in _all(spans(ev, {"providers": {}})) if s["name"] == "lane.attempt"]
    raw = {a["key"]: a["value"] for a in span["attributes"]}
    assert raw["gen_ai.usage.input_tokens"] == {"intValue": "3"}
    assert raw["gen_ai.usage.output_tokens"] == {"intValue": "4"}


def test_attempt_falls_back_to_latest_attempt_event_when_no_experiment():
    ev = [_claim(),
          make_event("attempt.finished", {"attempt_id": "aa-a1", "outcome": "succeeded",
                                          "exit_code": 0, "head_sha": "0" * 40},
                     item_id="aa", ts="2026-11-07T12:03:00Z")]
    (span,) = [s for s in _all(spans(ev, {"providers": {}})) if s["name"] == "lane.attempt"]
    assert span["endTimeUnixNano"] == str((1794052800 + 180) * 10 ** 9)
    assert "lanectl.decision" not in _attrs(span)


def test_operator_session_role_defaults_to_interactive():
    ev = [make_event("usage.recorded", {"provider": "anthropic",
                                        "source": "claude-code-interactive",
                                        "session_id": "s1", "model": C,
                                        "units": {"output_tokens": 2}},
                     item_id="aa", ts="2026-11-07T12:05:00Z")]
    (op,) = [s for s in _all(spans(ev, {})) if s["name"] == "operator.session"]
    assert _attrs(op)["lanectl.role"] == "interactive"
    assert op["spanId"] == _h("s1" + "2026-11-07T12:05:00Z", 16)


def test_usage_without_item_id_is_not_a_session():
    ev = [make_event("usage.recorded", {"provider": "anthropic",
                                        "source": "claude-code-interactive",
                                        "session_id": "s2", "model": C,
                                        "units": {"output_tokens": 1}})]
    assert _all(spans(ev, {})) == []


def test_unpriced_model_omits_cost_but_keeps_tokens():
    policy = {"providers": {"opencode": {"prices": {"models": {}}}}}
    ev = [_claim(), _usage({"input_tokens": 10, "output_tokens": 20})]
    (span,) = [s for s in _all(spans(ev, policy)) if s["name"] == "lane.attempt"]
    a = _attrs(span)
    assert "lanectl.cost_usd_est" not in a
    assert a["gen_ai.usage.input_tokens"] == 10 and a["gen_ai.usage.output_tokens"] == 20


def test_tokens_sum_over_multiple_usage_events():
    ev = [_claim(),
          _usage({"input_tokens": 100, "output_tokens": 50}, ts="2026-11-07T12:01:00Z"),
          _usage({"input_tokens": 7, "output_tokens": 3}, ts="2026-11-07T12:01:30Z")]
    (span,) = [s for s in _all(spans(ev, {"providers": {}})) if s["name"] == "lane.attempt"]
    a = _attrs(span)
    assert a["gen_ai.usage.input_tokens"] == 107
    assert a["gen_ai.usage.output_tokens"] == 53
