"""Extra coverage: outside-scope usage is not charged as unknown attribution."""
import pytest

from lanectl.accounting import accounting_timeline, render_timeline
from lanectl.contracts import make_event


POLICY = {"revision": 19, "providers": {"test": {"prices": {
    "models": {"model-a": {"offpeak": {"input": 1.0, "output": 2.0}}}}}}}


def usage(item, attempt=None, tokens=1_000_000):
    return make_event("usage.recorded", dict(
        provider="test", source="adapter", model="model-a",
        units={"output_tokens": tokens}, attempt_id=attempt), item_id=item)


def test_real_stream_splits_known_other_work_from_truly_unassigned():
    events = ([usage("ui-08-accounting")] * 3
              + [usage(f"other-work-{n % 7}") for n in range(101)]
              + [usage(None) for _ in range(196)])
    result = accounting_timeline(events, POLICY, item_id="ui-08-accounting")
    counts = result["attribution"]
    assert counts["attributed_events"] == 3
    assert counts["outside_scope_events"] == 101
    assert counts["unattributed_events"] == 196
    assert counts["coverage"] is None
    # Only the three selected records are ever charged.
    assert result["usage"]["lane"]["units"]["output_tokens"] == 3_000_000
    text = render_timeline(result)
    assert "outside_scope=101" in text and "coverage=unknown" in text


def test_full_coverage_requires_selected_records_and_no_unassigned_pool():
    result = accounting_timeline([usage("target-work")], POLICY, item_id="target-work")
    counts = result["attribution"]
    assert counts["coverage"] == 1.0 and counts["unattributed_events"] == 0
    assert "coverage=1.000" in render_timeline(result)


@pytest.mark.parametrize("events", [[], [usage(None)]])
def test_absent_or_unassigned_observations_never_prove_full_coverage(events):
    counts = accounting_timeline(events, POLICY, item_id="target-work")["attribution"]
    assert counts["coverage"] is None
    assert counts["attributed_events"] == 0


def test_attempt_query_never_charges_release_level_or_unknown_records():
    events = [usage("target-work", "aa-a1"),
              usage("target-work", "aa-a2"),
              usage("target-work"),
              usage("other-work", "aa-a1"),
              usage(None, "aa-a1")]
    counts = accounting_timeline(events, POLICY, item_id="target-work",
                                 attempt_id="aa-a1")["attribution"]
    assert counts["attributed_events"] == 1
    assert counts["outside_scope_events"] == 3   # other attempt, release, other item
    assert counts["unattributed_events"] == 1    # no item identity at all
    assert counts["coverage"] is None
