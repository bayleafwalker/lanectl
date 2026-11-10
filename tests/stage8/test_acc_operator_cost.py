"""Acceptance: operator cost per landed release (planner-owned)."""
import pytest

from lanectl.contracts import make_event
from lanectl.costs import price_usage
from lanectl.operator_cost import operator_cost, report_section

L, C = "opencode-go/deepseek-v4.1-flash", "claude-opus-5-5"
LANE_PRICES = {"peak_hours_utc": [], "peak_weekdays": [],
               "models": {L: {"offpeak": {"input": 1.0, "output": 2.0}}}}
OP_PRICES = {"peak_hours_utc": [], "peak_weekdays": [],
             "models": {C: {"offpeak": {"input": 10.0, "output": 20.0, "cache_read": 1.0,
                                        "cache_write": 5.0}}}}
POLICY = {"revision": 1, "providers": {
    "opencode": {"unit": "output_tokens", "prices": LANE_PRICES},
    "anthropic": {"unit": "output_tokens", "prices": OP_PRICES}}}
M = 1_000_000
TS = "2026-11-07T12:00:00Z"
OP = "claude-code-interactive"


def _usage(item, source, model, units):
    return make_event("usage.recorded", {"provider": "x", "source": source, "model": model,
                                         "units": units}, item_id=item, ts=TS)


def _landed(item):
    return make_event("item.landed", {"attempt_id": f"{item}-a1", "train_id": "t",
                                      "fix_commits": []}, item_id=item, ts=TS)


EVENTS = [
    _usage("aa", "adapter", L, {"output_tokens": M}),            # lane 2.00
    _usage("aa", OP, C, {"input_tokens": M}),                    # operator 10.00
    _landed("aa"),
    _usage("bb", "adapter", L, {"input_tokens": M}),             # lane 1.00, not landed
    _usage(None, OP, C, {"output_tokens": M}),                   # unattributed 20.00
    _usage("aa", OP, "claude-unknown", {"output_tokens": M}),    # unpriced
]


def test_cache_write_is_priced_when_the_tier_lists_it():
    assert price_usage({"cache_write_tokens": M}, C, TS, OP_PRICES) == pytest.approx(5.0)
    assert price_usage({"cache_write_tokens": M}, L, TS, LANE_PRICES) == pytest.approx(0.0)


def test_operator_cost_per_release_and_per_landed():
    s = operator_cost(EVENTS, POLICY)
    aa, bb = s["releases"]["aa"], s["releases"]["bb"]
    assert aa["lane_usd"] == pytest.approx(2.0) and aa["operator_usd"] == pytest.approx(10.0)
    assert aa["landed"] is True and bb["landed"] is False
    assert bb["lane_usd"] == pytest.approx(1.0) and bb["operator_usd"] == pytest.approx(0.0)
    assert s["landed"] == 1
    assert s["lane_usd_per_landed"] == pytest.approx(2.0)
    assert s["operator_usd_per_landed"] == pytest.approx(10.0)
    assert s["unattributed_operator_usd"] == pytest.approx(20.0)
    assert s["unpriced_events"] == 1


def test_nothing_landed_has_no_per_landed_figure():
    s = operator_cost(EVENTS[:2], POLICY)
    assert s["landed"] == 0
    assert s["lane_usd_per_landed"] is None and s["operator_usd_per_landed"] is None


def test_report_section_text():
    name, fn, fmt = report_section()
    assert name == "operator_cost"
    text = "\n".join(fmt(operator_cost(EVENTS, POLICY)))
    assert "operator_cost" in text
    assert "landed=1" in text and "lane_usd/landed=2.00" in text
    assert "operator_usd/landed=10.00" in text
    assert "unattributed_operator_usd=20.00" in text and "unpriced=1" in text
