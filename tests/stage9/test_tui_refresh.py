"""UI-04 refresh/offline contract coverage with injected readers and clock."""
from datetime import datetime, timedelta, timezone

from lanectl.tui import (
    initial_refresh_state, refresh_state, render_plain_table, render_screen,
)


NOW = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)


def stamp(when=NOW):
    return when.isoformat().replace("+00:00", "Z")


def event(item, attempt):
    return {"type": "item.claimed", "item_id": item, "ts": stamp(),
            "data": {"attempt_id": attempt, "lane": "implement", "model": "m", "worker": "w"}}


def owner(events, revision=None):
    rows = [{"item_id": e["item_id"], "attempt_id": e["data"]["attempt_id"], "facts": {
        "work.public.item-v1": {"state": "observed", "source": "owner", "revision": "r7", "observed_at": stamp(), "value": {"state": "active"}},
        "local.attempt": {"state": "observed", "source": "lanectl.events", "checkpoint": i + 1, "observed_at": stamp(), "value": [e]},
    }, "reasons": []} for i, e in enumerate(events)]
    return {"ready": {"state": "observed", "source": "owner", "revision": "r7", "observed_at": stamp(), "value": {"items": [e["item_id"] for e in events]}}, "rows": rows, "observed_at": stamp()}


def test_outage_keeps_cached_owner_rows_and_advances_events_independently():
    state = initial_refresh_state()
    state = refresh_state(state, lambda checkpoint: ([event("one", "a1")], 1), owner,
                          now=NOW, random_value=lambda: .5)
    state = refresh_state(state, lambda checkpoint: ([event("two", "a2")], 2),
                          lambda events, revision: (_ for _ in ()).throw(RuntimeError("owner down")),
                          now=NOW + timedelta(seconds=1), random_value=lambda: .5)
    snapshot = state["snapshot"]
    assert [row["item_id"] for row in snapshot["rows"]] == ["one", "two"]
    assert snapshot["sources"]["events"]["checkpoint"] == 2
    assert snapshot["sources"]["owner"]["state"] == "offline"
    assert snapshot["actions_allowed"] is False
    screen = render_screen(snapshot, "Active", width=120, height=24)
    assert "OWNER OFFLINE" in screen and "actions disabled" in screen
    assert "one" in render_plain_table(snapshot, "Active") and "OWNER OFFLINE" in render_plain_table(snapshot, "Active")


def test_reconnect_resumes_checkpoint_without_duplicate_rows():
    state = initial_refresh_state()
    state = refresh_state(state, lambda checkpoint: ([event("one", "a1")], 1), owner,
                          now=NOW, random_value=lambda: .5)
    state = refresh_state(state, lambda checkpoint: ([event("one", "a1"), event("two", "a2")], 2), owner,
                          now=NOW + timedelta(seconds=1), random_value=lambda: .5)
    assert state["event_checkpoint"] == 2
    assert [row["item_id"] for row in state["snapshot"]["rows"]] == ["one", "two"]


def test_backoff_is_bounded_monotonic_and_jittered():
    state = initial_refresh_state()
    reader = lambda checkpoint: ([], checkpoint or 0)
    down = lambda events, revision: (_ for _ in ()).throw(RuntimeError("down"))
    delays = []
    for index in range(6):
        now = NOW + timedelta(seconds=1000 * index)
        state = refresh_state(state, reader, down, now=now, random_value=lambda: 1.0,
                              backoff_base_s=2, backoff_cap_s=20)
        delays.append((state["next_owner_attempt_at"] - now).total_seconds())
    assert delays == [3, 6, 12, 20, 20, 20]


def test_stale_owner_disables_actions_and_fresh_owner_enables_them():
    state = initial_refresh_state()
    state = refresh_state(state, lambda checkpoint: ([event("one", "a1")], 1), owner,
                          now=NOW, random_value=lambda: .5, stale_after_s=10)
    assert state["snapshot"]["actions_allowed"] is True
    state = refresh_state(state, lambda checkpoint: ([], checkpoint),
                          lambda events, revision: (_ for _ in ()).throw(RuntimeError("down")),
                          now=NOW + timedelta(seconds=11), random_value=lambda: .5, stale_after_s=10)
    assert state["snapshot"]["sources"]["owner"]["state"] == "stale"
    assert state["snapshot"]["actions_allowed"] is False
    assert "age 11s" in render_plain_table(state["snapshot"], "Active")
