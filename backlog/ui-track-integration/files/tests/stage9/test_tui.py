"""UI-03 view-model and rendering coverage without a terminal."""
from lanectl.tui import (
    ACTIVE, READY, VERIFICATION, build_snapshot, focus_index, handle_key,
    initial_state, render_plain_table, render_screen, view_rows,
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


def test_refresh_keeps_inspection_on_same_identity_after_reorder():
    before = snapshot()
    state = initial_state(before, ACTIVE)
    state = handle_key(state, "j")
    state = handle_key(state, "enter")
    assert state["detail"] == (("owner#2", "a2"), "detail")
    reordered = build_snapshot(before["ready"], [row("owner#2", "a2"), row("owner#1", "a1")])
    state = handle_key(state, "refresh", snapshot=reordered)
    screen = render_screen(state["snapshot"], state["view"], width=100, height=24,
                           selected=state["selected"], detail=state["detail"])
    assert state["detail"][0] == ("owner#2", "a2")
    assert "DETAIL owner#2" in screen
    assert "DETAIL owner#1" not in screen


def test_refresh_reports_inspected_item_that_left_view():
    before = snapshot()
    state = handle_key(initial_state(before, ACTIVE), "enter")
    remaining = build_snapshot(before["ready"], [row("owner#2", "a2")])
    state = handle_key(state, "refresh", snapshot=remaining)
    screen = render_screen(state["snapshot"], state["view"], width=100, height=24,
                           selected=state["selected"], detail=state["detail"])
    assert "item no longer in view" in screen
    assert "DETAIL owner#2" not in screen


def test_interactive_filter_apply_cancel_clear_and_keep_selection():
    state = initial_state(snapshot(), ACTIVE)
    state = handle_key(state, "j")
    state = handle_key(state, "/")
    state = handle_key(state, ord("#"))
    state = handle_key(state, ord("2"))
    state = handle_key(state, "enter")
    assert state["filter"] == "#2"
    assert state["selection"] == ("owner#2", "a2")
    assert [r["item_id"] for r in view_rows(state["snapshot"], state["view"], state["filter"])] == ["owner#2"]

    state = handle_key(state, "/")
    state = handle_key(state, ord("x"))
    state = handle_key(state, "esc")
    assert state["filter"] == "#2" and not state["filtering"]
    state = handle_key(state, "/")
    state = handle_key(state, "backspace")
    state = handle_key(state, "backspace")
    state = handle_key(state, "enter")
    assert state["filter"] == ""
    assert state["selection"] == ("owner#2", "a2")


def test_help_and_sources_are_distinct_overlays():
    state = initial_state(snapshot(), ACTIVE)
    help_state = handle_key(state, "?")
    help_screen = render_screen(help_state["snapshot"], help_state["view"], width=100,
                                height=24, help=help_state["help"])
    assert "HELP" in help_screen and "Enter inspect" in help_screen and "s sources" in help_screen

    sourced = row("owner#1", "a1")
    sourced["facts"]["work.public.item-v1"]["value"]["reference"] = "https://example.test/item"
    sourced["facts"]["work.public.item-v1"]["value"]["path"] = "/srv/items/owner-1"
    source_snapshot = build_snapshot(fact("work.public.list-v1", {"items": ["owner#1"]}), [sourced])
    source_state = handle_key(initial_state(source_snapshot, READY), "s")
    screen = render_screen(source_state["snapshot"], source_state["view"], width=120,
                           height=24, detail=source_state["detail"])
    assert "SOURCES owner#1" in screen
    assert "source=work.public.item-v1" in screen and "revision=r7" in screen
    assert "https://example.test/item" in screen and "/srv/items/owner-1" not in screen
    assert "value:" not in screen
