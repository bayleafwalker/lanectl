import pytest

from lanectl.accounting import accounting_timeline
from lanectl.contracts import make_event


POLICY = {"revision": 19, "providers": {"test": {"prices": {"models": {
    "model-a": {"offpeak": {"input": 1.0, "output": 2.0}}}}}}}


def usage(units, model="model-a"):
    return make_event("usage.recorded", dict(provider="test", source="adapter",
        model=model, units=units), item_id="subtotal-work", ts="2026-11-12T10:00:00Z")


def lane(events, policy=POLICY):
    return accounting_timeline(events, policy, item_id="subtotal-work")["usage"]["lane"]


def test_real_steps_metadata_does_not_erase_known_token_subtotal():
    result = lane([usage(dict(input_tokens=1_000_000, output_tokens=1_000_000, steps=79, cost_usd=0.0))])
    assert result["usd_est"] is None
    assert result["known_usd_est"] == pytest.approx(3.0)
    assert result["unpriced_events"] == 1 and result["priced_events"] == 0
    assert result["units"]["steps"] == 79


def test_partial_rate_keeps_its_known_component_and_unknowns_stay_unknown():
    from copy import deepcopy
    policy = deepcopy(POLICY)
    del policy["providers"]["test"]["prices"]["models"]["model-a"]["offpeak"]["output"]
    result = lane([usage(dict(input_tokens=100, output_tokens=50))], policy)
    assert result["usd_est"] is None and result["known_usd_est"] == pytest.approx(0.0001)
    for event in (usage({"steps": 3}), usage({"output_tokens": 10}, model="unknown"), usage({})):
        result = lane([event])
        assert result["usd_est"] is None and result["known_usd_est"] is None


def test_known_components_sum_once_across_complete_and_partial_events():
    result = lane([usage(dict(output_tokens=1_000_000)),
                   usage(dict(output_tokens=1_000_000, steps=2))])
    assert result["known_usd_est"] == pytest.approx(4.0)
    assert result["usd_est"] is None
    assert result["priced_events"] == 1 and result["unpriced_events"] == 1
