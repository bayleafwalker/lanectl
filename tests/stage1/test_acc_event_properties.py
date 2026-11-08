"""Acceptance: events round-trip through the contract and the projection is total
(planner writes the properties; the lane writes the generators in tests/strategies.py)."""
import json

from hypothesis import given, settings

from lanectl.contracts import EVENT_TYPES, ITEM_STATES, validate_event
from lanectl.events import EventLog, project_items
from tests.strategies import event_logs, valid_events


@given(valid_events())
@settings(max_examples=300)
def test_valid_events_round_trip(ev):
    assert ev["type"] in EVENT_TYPES
    assert validate_event(json.loads(json.dumps(ev))) == ev


@given(event_logs())
@settings(max_examples=200)
def test_projection_is_total_and_states_are_known(log):
    items = project_items(log)
    assert all(v.state in ITEM_STATES for v in items.values())
    claimed = sum(1 for e in log if e["type"] == "item.claimed")
    assert sum(len(v.attempts) for v in items.values()) == claimed


@given(event_logs())
@settings(max_examples=50, deadline=None)
def test_log_persistence_round_trip(tmp_path_factory, log):
    path = tmp_path_factory.mktemp("log") / "events.jsonl"
    el = EventLog(path)
    for ev in log:
        el.append(ev["type"], ev["data"], item_id=ev["item_id"])
    back = el.read()
    assert [(e["type"], e["item_id"], e["data"]) for e in back] == [(e["type"], e["item_id"], e["data"]) for e in log]
