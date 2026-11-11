"""UI-03 view-model and rendering coverage without a terminal."""
from lanectl.tui import (
    ACTIVE, READY, VERIFICATION, build_snapshot, focus_index, render_plain_table,
    render_screen, view_rows,
)


def fact(name, value, *, state="observed"):
    return {"state": state, "source": name, "revision": "r7",
            "observed_at": "2026-11-11T12:41:08Z", **({"value": value} if state == "observed" else {"reason": "unavailable"})}


def row(item, attempt, *, owner="active", train=False):
    facts = {
        "work.public.item-v1": fact("work.public.item-v1", {"state": owner}),
        "work.lease.read-v1": fact("work.lease.read-v1", {"lease": "active"}),
        "local.attempt": fact("lanectl.events", [{"type": "item.claimed", "data": {"attempt_id": attempt}}]),
        "local.train": fact("lanectl.events", ([{"type": "train.built", "data": {"train_id": "t-1", "passed": True}}] if train else [])),
    }
    return {"item_id": item, "attempt_id": attempt, "facts": facts,
            "reasons": [{"code": "pending-verification", "evidence": [{"fact": "work.public.item-v1", "identifiers": {"item_id": item}}], "next_actions": ["read owner"]}] if owner == "awaiting-verification" else []}


def snapshot():
    return build_snapshot(fact("work.public.list-v1", {"items": ["owner#2", "owner#1"]}), [
        row("owner#1", "a1"), row("owner#2", "a2", owner="awaiting-verification", train=True),
    ])


def test_three_views_filter_and_owner_order():
    state = snapshot()
    assert [r["item_id"] for r in view_rows(state, READY)] == ["owner#2", "owner#1"]
    assert [r["item_id"] for r in view_rows(state, ACTIVE)] == ["owner#1", "owner#2"]
    assert [r["item_id"] for r in view_rows(state, VERIFICATION)] == ["owner#2"]
    assert [r["item_id"] for r in view_rows(state, READY, "#1")] == ["owner#1"]


def test_focus_is_stable_when_rows_reorder_or_update():
    old = view_rows(snapshot(), ACTIVE)
    changed = build_snapshot(fact("work.public.list-v1", {"items": []}), [row("owner#2", "a2"), row("owner#1", "a1")])
    assert focus_index(old, 1, view_rows(changed, ACTIVE)) == 0
    assert focus_index(old, 1, []) is None


def test_eighty_column_screen_truncates_and_needs_no_color_markers():
    state = snapshot()
    screen = render_screen(state, ACTIVE, width=80, height=24, selected=0, color=False)
    assert all(len(line) <= 80 for line in screen.splitlines())
    assert ">" in screen and "active" in screen.lower()
    assert "\x1b[" not in screen


def test_plain_table_is_same_view_model_query_snapshot():
    state = snapshot()
    rows = view_rows(state, VERIFICATION)
    table = render_plain_table(state, VERIFICATION)
    assert "owner#2" in table and "owner#1" not in table
    assert rows[0]["item_id"] in table
