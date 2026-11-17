"""Screen-size, scrolling, polling-rate and non-TTY behaviour of the operator TUI."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from lanectl import tui
from lanectl.tui import (ACTIVE, OwnerPoller, handle_key, initial_refresh_state, initial_state,
                         render_plain_table, render_screen)
from test_tui import snapshot

NOW = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)


def long_detail_state():
    state = snapshot()
    state["rows"][0]["reasons"] = [{"code": f"code-{i}", "evidence": [], "next_actions": ["x"]}
                                   for i in range(40)]
    return state


@pytest.mark.parametrize("width,height", [(80, 24), (40, 12)])
def test_frames_fit_the_terminal_and_end_with_the_footer(width, height):
    screen = render_screen(snapshot(), ACTIVE, width=width, height=height, selected=1)
    lines = screen.split("\n")
    assert len(lines) == height and all(len(line) <= width for line in lines)
    assert "? keys" in lines[-1] and "q quit" in lines[-1]
    assert "owner#2" in screen and "\x1b[" not in screen


def test_eighty_columns_show_status_age_once_and_the_full_footer():
    screen = render_screen(snapshot(), ACTIVE, width=80, height=24)
    status = screen.split("\n")[1]
    assert "updated 0s ago" in status and status.count("owner") == 1
    assert "." not in status.split("updated")[1].split("ago")[0]  # no microseconds
    assert "j/k move · Enter inspect · / filter · ? keys · q quit" in screen.split("\n")[-1]


def test_below_eighty_columns_rows_stack_and_keep_state_symbols():
    screen = render_screen(snapshot(), ACTIVE, width=40, height=12, selected=0)
    assert "WORK" not in screen  # no table header when stacked
    assert "> owner#1 a1" in screen and "◐ active" in screen and "▲ awaiting-verification"[:20] in screen


def test_list_scrolls_to_keep_the_selection_visible():
    rows = [dict(snapshot()["rows"][0], item_id=f"w{i}", attempt_id=f"a{i}") for i in range(30)]
    snap = tui.build_snapshot({"state": "observed", "value": {"items": []}}, rows)
    screen = render_screen(snap, ACTIVE, width=80, height=10, selected=25)
    assert "> w25" in screen and "w0 " not in screen


def test_detail_scrolls_with_keys_and_is_bounded():
    snap = long_detail_state()
    state = handle_key(initial_state(snap, ACTIVE), "enter")
    kw = {"height": 12, "width": 60}
    assert state["scroll"] == 0
    state = handle_key(state, "j", **kw)
    assert state["scroll"] == 1
    state = handle_key(state, "k", **kw)
    state = handle_key(state, "k", **kw)
    assert state["scroll"] == 0
    state = handle_key(state, tui.curses.KEY_NPAGE, **kw)
    assert state["scroll"] == 8
    state = handle_key(state, "G", **kw)
    _, lines = tui.overlay_lines(snap, ACTIVE, "", state["detail"], False, width=60)
    assert state["scroll"] == len(lines) - 8
    assert lines[-1] in render_screen(snap, ACTIVE, width=60, height=12, detail=state["detail"],
                                      scroll=state["scroll"])
    state = handle_key(handle_key(state, "j", **kw), tui.curses.KEY_PPAGE, **kw)
    assert handle_key(state, "g", **kw)["scroll"] == 0
    assert handle_key(state, "esc", **kw)["detail"] is None
    assert not handle_key(state, "esc", **kw).get("quit")


def test_footer_and_help_list_every_key_and_state():
    screen = render_screen(snapshot(), ACTIVE, width=80, height=40, help=True)
    for text in ("g/G", "PgDn", "filter", "evidence", "sources", "▲ needs you", "✗ failed",
                 "◐ running", "● ok/done", "○ idle/queued", "◌ unknown/stale"):
        assert text in screen


def test_plain_table_columns_are_aligned():
    lines = render_plain_table(snapshot(), ACTIVE).split("\n")[1:]
    assert len({line.index("LEASE") if "LEASE" in line else line.rindex("active") for line in lines}) == 1


class FakeWorker:
    started = 0

    def __init__(self, reader, events, revision):
        type(self).started += 1

    def poll(self):
        return ({"ready": {"state": "observed", "revision": "r"}, "rows": []}, None)


def test_owner_is_polled_once_per_interval_not_per_wakeup():
    FakeWorker.started = 0
    clock = {"t": 0.0}
    poller = OwnerPoller(None, 15, clock=lambda: clock["t"], worker=FakeWorker)
    refresh, now = initial_refresh_state(), NOW
    for _ in range(600):  # 60 s of 100 ms wakeups; each success resets backoff to None
        refresh, _ = poller.step(refresh, now)
        clock["t"] += 0.1
        now += timedelta(seconds=0.1)
    assert FakeWorker.started == 4  # t=0, 15, 30, 45


def test_failed_owner_read_still_honours_backoff_and_interval():
    FakeWorker.started = 0
    clock = {"t": 0.0}
    poller = OwnerPoller(None, 1, clock=lambda: clock["t"], worker=FakeWorker)
    refresh = dict(initial_refresh_state(), next_owner_attempt_at=NOW + timedelta(seconds=30))
    assert not poller.due(refresh, NOW) and poller.due(refresh, NOW + timedelta(seconds=31))


def args(**kw):
    kw.setdefault("plain", True)   # off a TTY without --plain the TUI prints `status` instead
    return SimpleNamespace(repo="r", view="ready", filter="", item=None, attempt=None,
                           no_color=False, refresh=15.0, **kw)


def test_plain_prints_the_query_table_and_exits_zero(monkeypatch, capsys):
    from lanectl import coordination, config
    monkeypatch.setattr(coordination, "configured", lambda repo: SimpleNamespace(client=None, path=None))
    monkeypatch.setattr(config, "load_releases", lambda: [])
    monkeypatch.setattr(tui, "query_snapshot", lambda *a, **k: snapshot())
    monkeypatch.setattr(tui, "_interactive", lambda: False)
    assert tui._cmd(args(), SimpleNamespace(read=lambda after=0: []))== 0
    out = capsys.readouterr().out
    assert "owner#1" in out and "WORK" in out


def test_unconfigured_error_names_file_table_docs_and_fails(monkeypatch, capsys):
    from lanectl import coordination
    monkeypatch.setattr(coordination, "configured", lambda repo: None)
    assert tui._cmd(args(), None) == 1
    err = capsys.readouterr().err
    assert "governance/vuoro.toml" in err and "[repos.r]" in err and "vuoro-coordination.md" in err


def test_no_color_is_honoured(monkeypatch):
    monkeypatch.setattr(tui.curses, "has_colors", lambda: True)
    assert tui._use_color(False)
    assert not tui._use_color(True)
    monkeypatch.setenv("NO_COLOR", "1")
    assert not tui._use_color(False)
