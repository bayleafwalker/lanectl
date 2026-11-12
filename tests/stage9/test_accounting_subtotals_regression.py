"""Regressions for retaining priced token subtotals in partly priced usage.

Actual lane records carry metadata units such as ``steps`` next to priced
tokens, so a single unknown unit must not erase the known token subtotal.
"""
from copy import deepcopy

import pytest

from lanectl.accounting import accounting_timeline
from lanectl.contracts import make_event


POLICY = {"revision": 19, "providers": {"test": {"prices": {"models": {
    "model-a": {"offpeak": {"input": 1.0, "output": 2.0}}}}}}}


def usage(units, model="model-a"):
    return make_event("usage.recorded", dict(provider="test", source="adapter",
        model=model, units=units), item_id="subtotal-work",
        ts="2026-11-12T10:00:00Z")


def lane(events, policy=POLICY):
    return accounting_timeline(events, policy, item_id="subtotal-work")["usage"]["lane"]


def test_steps_and_cost_metadata_keep_the_priced_token_subtotal():
    result = lane([usage(dict(input_tokens=1_000_000, output_tokens=1_000_000,
                              steps=79, cost_usd=0.0))])
    assert result["usd_est"] is None
    assert result["known_usd_est"] == pytest.approx(3.0)
    assert result["priced_events"] == 0
    assert result["unpriced_events"] == 1
    assert result["units"]["steps"] == 79
    assert result["units"]["input_tokens"] == 1_000_000


def test_partially_missing_rate_columns_keep_only_their_known_components():
    policy = deepcopy(POLICY)
    del policy["providers"]["test"]["prices"]["models"]["model-a"]["offpeak"]["output"]
    result = lane([usage(dict(input_tokens=100, output_tokens=50,
                              reasoning_tokens=10))], policy)
    assert result["usd_est"] is None
    assert result["known_usd_est"] == pytest.approx(0.0001)
    assert result["unpriced_events"] == 1

    # A zero-valued token with a known rate is a measured zero, not unknown.
    zero = lane([usage(dict(input_tokens=0, steps=4))])
    assert zero["known_usd_est"] == pytest.approx(0.0)
    assert zero["usd_est"] is None


def test_all_unknown_data_stays_unknown_not_zero():
    cases = [usage({"mystery_units": 3}),
             usage({"output_tokens": "unknown"}),
             usage({"output_tokens": 10}, model="missing-model"),
             usage({})]
    for event in cases:
        result = lane([event])
        assert result["usd_est"] is None
        assert result["known_usd_est"] is None
        assert result["unpriced_events"] == 1
        assert result["priced_events"] == 0

    # Unknown units never zero out the token components priced beside them.
    mixed = lane([usage(dict(output_tokens=1_000_000, mystery_units=2)),
                  usage({"mystery_units": 5})])
    assert mixed["usd_est"] is None
    assert mixed["known_usd_est"] == pytest.approx(2.0)
    assert mixed["unpriced_events"] == 2


def test_known_components_sum_once_across_complete_and_partial_records():
    result = lane([usage(dict(input_tokens=1_000_000)),
                   usage(dict(output_tokens=1_000_000, steps=2))])
    assert result["known_usd_est"] == pytest.approx(3.0)
    assert result["usd_est"] is None
    assert result["priced_events"] == 1
    assert result["unpriced_events"] == 1
    assert result["events"] == 2
    assert result["units"]["input_tokens"] == 1_000_000
    assert result["units"]["output_tokens"] == 1_000_000
    assert result["units"]["steps"] == 2
