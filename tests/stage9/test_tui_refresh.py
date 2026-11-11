"""UI-04 refresh/offline contract coverage with injected readers and clock."""
from datetime import datetime, timedelta, timezone
from threading import Event

from lanectl.tui import (
    OwnerRefreshWorker, handle_key, initial_refresh_state, initial_state,
    query_snapshot, refresh_state, render_plain_table, render_screen,
)
from lanectl.coordination import CoordinationError
from test_lifecycle import Client


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
    def resumed(checkpoint):
        assert checkpoint == 1
        return [event("two", "a2")], 2
    state = refresh_state(state, resumed, owner,
                          now=NOW + timedelta(seconds=1), random_value=lambda: .5)
    assert state["event_checkpoint"] == 2
    assert [row["item_id"] for row in state["snapshot"]["rows"]] == ["one", "two"]


def test_refused_lifecycle_read_is_an_owner_outage_and_keeps_last_good_facts():
    event44 = event(44, "a1")
    state = initial_refresh_state()
    state = refresh_state(state, lambda checkpoint: ([event44], 1),
                          lambda events, revision: query_snapshot(Client(), events), now=NOW)
    observed = state["snapshot"]["rows"][0]["facts"]["work.public.item-v1"]["observed_at"]

    class RefusingClient(Client):
        def invoke(self, envelope):
            if envelope["operation"] == "work.lease.read-v1":
                raise CoordinationError("owner refused: runner-operation-denied (HTTP 403)")
            return super().invoke(envelope)

    state = refresh_state(state, lambda checkpoint: ([], checkpoint),
                          lambda events, revision: query_snapshot(RefusingClient(), events),
                          now=NOW + timedelta(seconds=1), random_value=lambda: 0)
    snapshot = state["snapshot"]
    assert snapshot["sources"]["owner"]["state"] == "offline"
    assert snapshot["actions_allowed"] is False
    assert state["owner_failures"] == 1 and state["next_owner_attempt_at"] > NOW
    assert snapshot["rows"][0]["facts"]["work.public.item-v1"]["observed_at"] == observed
    assert "OWNER OFFLINE" in render_plain_table(snapshot, "Active")


def test_slow_real_query_runs_outside_key_handling_with_injected_clock():
    entered, release = Event(), Event()

    class SlowClient(Client):
        def invoke(self, envelope):
            entered.set()
            assert release.wait(1)
            return super().invoke(envelope)

    ticks = iter((10.0, 11.0))
    worker = OwnerRefreshWorker(lambda events, revision: query_snapshot(SlowClient(), events),
                                [event(44, "a1")], None, clock=lambda: next(ticks))
    assert entered.wait(.2) and worker.poll() is None
    state = initial_state({"ready": {"value": {"items": []}}, "rows": []})
    assert handle_key(state, "j") == state  # key transition does not await owner I/O
    release.set()
    worker._thread.join(1)
    result, error = worker.poll()
    assert error is None and result["rows"][0]["item_id"] == 44 and worker.started_at == 10.0


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
