from lanectl.accounting import accounting_timeline, render_timeline
from lanectl.contracts import make_event


def usage(item, attempt=None):
    return make_event("usage.recorded", dict(provider="test", source="adapter", model="model-a",
        units={"output_tokens": 1_000_000}, attempt_id=attempt), item_id=item)


def test_other_assigned_work_is_outside_scope_not_unknown_attribution():
    result = accounting_timeline([usage("target-work"), usage("other-work"), usage(None)], {}, item_id="target-work")
    counts = result["attribution"]
    assert counts["attributed_events"] == 1 and counts["unattributed_events"] == 1
    assert counts.get("outside_scope_events") == 1 and counts.get("coverage") is None
    assert "observed" in counts.get("basis", "")
    assert result["usage"]["lane"]["units"]["output_tokens"] == 1_000_000
    text = render_timeline(result)
    assert "coverage=unknown" in text and "outside_scope=1" in text


def test_attempt_scope_excludes_known_release_and_other_attempt_records():
    events = [usage("target-work", "aa-a1"), usage("target-work", "aa-a2"), usage("target-work")]
    counts = accounting_timeline(events, {}, item_id="target-work", attempt_id="aa-a1")["attribution"]
    assert counts["attributed_events"] == 1 and counts["unattributed_events"] == 0
    assert counts.get("outside_scope_events") == 2 and counts.get("coverage") == 1.0
    absent = accounting_timeline(events, {}, item_id="absent-work")["attribution"]
    assert absent.get("coverage") is None and absent.get("outside_scope_events") == 3
