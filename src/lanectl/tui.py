"""Read-only operator TUI for lifecycle snapshots.

The view-model functions in this module have no terminal or owner I/O.  The
small curses adapter below them only obtains a new snapshot and renders it.
"""
from __future__ import annotations

from datetime import datetime, timezone
import curses
import os
import time

from .lifecycle import attention_reasons, lifecycle_rows, ready_work

READY = "Ready"
ACTIVE = "Active"
VERIFICATION = "Verification"
VIEWS = (READY, ACTIVE, VERIFICATION)


def _text(value):
    return "-" if value is None else str(value)


def _identity(row):
    return (row.get("item_id"), row.get("attempt_id"))


def _facts(row):
    return row.get("facts", {})


def _state(row):
    return _facts(row).get("work.public.item-v1", {}).get("value", {}).get("state", "unknown")


def _has_events(row, name):
    return bool(_facts(row).get(name, {}).get("value", []))


def build_snapshot(ready, rows, *, observed_at=None):
    """Build a coherent display input from lifecycle query results.

    ``ready`` and ``rows`` retain the source facts unchanged, making the
    detail pane auditable rather than a second lifecycle ledger.
    """
    return {"ready": ready, "rows": list(rows),
            "observed_at": observed_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}


def view_rows(snapshot, view, filter_text=""):
    """Return normalized rows for a view, preserving owner order for Ready."""
    all_rows = snapshot.get("rows", [])
    by_item = {}
    for row in all_rows:
        by_item.setdefault(_text(row.get("item_id")), row)
    if view == READY:
        items = snapshot.get("ready", {}).get("value", {}).get("items", [])
        rows = []
        for item in items:
            key = _text(item)
            rows.append(by_item.get(key, {"item_id": item, "attempt_id": None, "facts": {}, "reasons": []}))
    elif view == ACTIVE:
        rows = [row for row in all_rows if _has_events(row, "local.attempt") or
                _facts(row).get("work.lease.read-v1", {}).get("state") == "observed"]
    elif view == VERIFICATION:
        rows = [row for row in all_rows if _state(row) in ("pending-verification", "awaiting-verification")
                or _has_events(row, "local.train") or _has_events(row, "local.receipt")]
    else:
        raise ValueError(f"unsupported view: {view}")
    needle = filter_text.casefold().strip()
    if not needle:
        return rows
    return [row for row in rows if needle in " ".join((_text(row.get("item_id")), _text(row.get("attempt_id")),
                                                         _state(row), " ".join(r.get("code", "") for r in row.get("reasons", [])))).casefold()]


def focus_index(previous_rows, selected, current_rows):
    """Keep focus on its identity after refresh, returning a safe new index."""
    if not current_rows:
        return None
    if previous_rows and selected is not None and 0 <= selected < len(previous_rows):
        wanted = _identity(previous_rows[selected])
        for index, row in enumerate(current_rows):
            if _identity(row) == wanted:
                return index
    return min(selected or 0, len(current_rows) - 1)


def initial_state(snapshot, view=READY, filter_text=""):
    rows = view_rows(snapshot, view, filter_text)
    return {"snapshot": snapshot, "view": view, "filter": filter_text,
            "selected": 0, "selection": _identity(rows[0]) if rows else None,
            "detail": None, "help": False, "filtering": False,
            "filter_draft": filter_text}


def _index_for(rows, identity):
    if identity is None:
        return None
    return next((i for i, row in enumerate(rows) if _identity(row) == identity), None)


def _reconcile(state, *, previous_rows=None):
    rows = view_rows(state["snapshot"], state["view"], state["filter"])
    selected = _index_for(rows, state.get("selection"))
    if selected is None:
        selected = focus_index(previous_rows or [], state.get("selected"), rows)
    state["selected"] = selected
    state["selection"] = _identity(rows[selected]) if selected is not None else None
    return state


def handle_key(state, key, *, snapshot=None):
    """Pure TUI state transition. ``snapshot`` supplies a refresh result."""
    state = dict(state)
    rows = view_rows(state["snapshot"], state["view"], state["filter"])
    if key == "refresh":
        if snapshot is not None:
            state["snapshot"] = snapshot
        return _reconcile(state, previous_rows=rows)
    if state.get("filtering"):
        if key in (10, 13, "enter"):
            state["filter"] = state.get("filter_draft", "").strip()
            state["filtering"] = False
            state["detail"] = None
            state["selection"] = state.get("selection")
            return _reconcile(state, previous_rows=rows)
        if key in (27, "esc"):
            state["filtering"] = False
            state["filter_draft"] = state["filter"]
            return state
        if key in (curses.KEY_BACKSPACE, 127, 8, "backspace"):
            state["filter_draft"] = state.get("filter_draft", "")[:-1]
        elif isinstance(key, int) and 32 <= key <= 126:
            state["filter_draft"] = state.get("filter_draft", "") + chr(key)
        elif isinstance(key, str) and len(key) == 1 and key.isprintable():
            state["filter_draft"] = state.get("filter_draft", "") + key
        return state
    if key in (ord("q"), 27, "q", "esc"):
        state["quit"] = True
    elif key in (ord("/"), "/"):
        state["filtering"] = True
        state["filter_draft"] = state["filter"]
    elif key in (ord("r"), "r"):
        if snapshot is not None:
            state["snapshot"] = snapshot
        return _reconcile(state, previous_rows=rows)
    elif key in (ord("1"), ord("2"), ord("3"), "1", "2", "3"):
        index = int(chr(key) if isinstance(key, int) else key) - 1
        state.update(view=VIEWS[index], selected=0, selection=None, detail=None, help=False)
        return _reconcile(state)
    elif key in (curses.KEY_DOWN, ord("j"), "down", "j") and rows:
        state["selected"] = min((state.get("selected") or 0) + 1, len(rows) - 1)
        state["selection"] = _identity(rows[state["selected"]])
    elif key in (curses.KEY_UP, ord("k"), "up", "k") and rows:
        state["selected"] = max((state.get("selected") or 0) - 1, 0)
        state["selection"] = _identity(rows[state["selected"]])
    elif key in (10, 13, "enter") and rows:
        state["detail"] = (state["selection"], "detail")
        state["help"] = False
    elif key in (ord("e"), "e") and rows:
        state["detail"] = (state["selection"], "evidence")
        state["help"] = False
    elif key in (ord("s"), "s") and rows:
        state["detail"] = (state["selection"], "sources")
        state["help"] = False
    elif key in (ord("?"), "?"):
        state["help"] = True
        state["detail"] = None
    return state


def _columns(view):
    if view == READY:
        return ("WORK", "ATTEMPT", "READINESS", "REASONS")
    if view == ACTIVE:
        return ("WORK", "ATTEMPT", "OWNER", "LEASE", "REASONS")
    return ("WORK", "ATTEMPT", "OUTCOME", "EVIDENCE", "REASONS")


def _cells(row, view):
    facts = _facts(row)
    codes = ",".join(reason.get("code", "") for reason in row.get("reasons", [])) or "-"
    lease = facts.get("work.lease.read-v1", {})
    lease_value = lease.get("value", {}).get("lease", lease.get("state", "unknown"))
    if view == READY:
        return (_text(row.get("item_id")), _text(row.get("attempt_id")), _state(row), codes)
    if view == ACTIVE:
        return (_text(row.get("item_id")), _text(row.get("attempt_id")), _state(row), _text(lease_value), codes)
    evidence = facts.get("work.evidence.tail-v1", {}).get("state", "local")
    return (_text(row.get("item_id")), _text(row.get("attempt_id")), _state(row), evidence, codes)


def _fit(cells, width, marker=""):
    gap = 2
    available = max(1, width - len(marker) - gap * (len(cells) - 1))
    weights = [2] + [1] * (len(cells) - 1)
    total = sum(weights)
    lengths = [max(3, available * weight // total) for weight in weights]
    lengths[-1] += available - sum(lengths)
    def clipped(value, size):
        value = _text(value)
        return value if len(value) <= size else value[:max(0, size - 1)] + "…"
    return marker + "  ".join(clipped(value, size).ljust(size) for value, size in zip(cells, lengths))


def render_plain_table(snapshot, view, filter_text=""):
    """Plain, no-color representation of exactly the displayed view query."""
    rows = view_rows(snapshot, view, filter_text)
    lines = ["  ".join(_columns(view))]
    lines.extend("  ".join(_cells(row, view)) for row in rows)
    return "\n".join(lines)


def detail_lines(row, *, evidence_only=False):
    """Render all selected facts with source, revision and observation time."""
    lines = []
    for name, fact in _facts(row).items():
        if evidence_only and "evidence" not in name:
            continue
        lines.append(f"{name}: {fact.get('state', 'unknown')} · source={fact.get('source', '-')} · rev={fact.get('revision', '-')} · observed={fact.get('observed_at', '-')}")
        if fact.get("state") == "observed":
            lines.append(f"  value: {_text(fact.get('value'))}")
        else:
            lines.append(f"  reason: {_text(fact.get('reason'))}")
    for reason in row.get("reasons", []):
        lines.append(f"reason {reason.get('code')}: evidence={_text(reason.get('evidence'))} · next={', '.join(reason.get('next_actions', []))}")
    if not evidence_only:
        links = [f"{name} -> {fact.get('source', '-')}" for name, fact in _facts(row).items()]
        if links:
            lines.append("source links: " + "; ".join(links))
    return lines or ["No facts were available for this row."]


def source_lines(row):
    """List fact provenance and URL/path references separately from detail."""
    lines = []
    references = set()
    def collect(value):
        if isinstance(value, dict):
            for child in value.values(): collect(child)
        elif isinstance(value, (list, tuple)):
            for child in value: collect(child)
        elif isinstance(value, str):
            for token in value.split():
                token = token.strip("()[]{}<>,;\"'")
                if token.startswith(("https://", "http://", "file://", "/", "./", "../")):
                    references.add(token)
    for name, fact in _facts(row).items():
        source = fact.get("source", "-")
        lines.append(f"{name}: source={source} · revision={fact.get('revision', '-')}")
        collect(source)
        collect(fact.get("value"))
    lines.extend(f"link: {reference}" for reference in sorted(references))
    return lines or ["No sources were available for this row."]


HELP_LINES = ["Keys: 1 Ready · 2 Active · 3 Verification", "j/↓ and k/↑ move selection",
              "/ filter · Enter inspect · e evidence · s sources", "r refresh · ? help · q quit"]


def render_screen(snapshot, view, *, width, height, selected=0, filter_text="", color=False, detail=None, help=False, filtering=False, filter_draft=""):
    """Render an 80x24-safe text frame; color is deliberately presentation-only."""
    del color  # state is always conveyed by words and markers.
    width, height = max(1, width), max(1, height)
    rows = view_rows(snapshot, view, filter_text)
    stamp = snapshot.get("observed_at", "unknown")
    shown_filter = filter_draft if filtering else filter_text
    lines = [f"{view} (read-only) · observed {stamp}", f"FILTER {shown_filter or '-'} · {len(rows)} rows",
             _fit(_columns(view), width)]
    if filtering:
        lines.append("FILTER TEXT (Enter apply · Esc cancel): " + filter_draft)
    if help:
        lines.append("HELP")
        lines.extend(HELP_LINES)
    elif detail is not None:
        identity, mode = detail if isinstance(detail, tuple) else (detail, "detail")
        detail_index = _index_for(rows, identity) if isinstance(identity, tuple) else identity
        if detail_index is None or detail_index >= len(rows):
            lines.extend(["DETAIL", "item no longer in view"])
        else:
            row = rows[detail_index]
            lines.append(("SOURCES " if mode == "sources" else "EVIDENCE " if mode in ("evidence", True) else "DETAIL ") + _text(row.get("item_id")))
            lines.extend(source_lines(row) if mode == "sources" else detail_lines(row, evidence_only=mode in ("evidence", True)))
    else:
        for index, row in enumerate(rows):
            lines.append(_fit(_cells(row, view), width, "> " if index == selected else "  "))
    footer = "1 Ready  2 Active  3 Verification  j/k move  / filter  r refresh  Enter inspect  e evidence  s sources  ? help  q quit"
    lines.append(footer)
    return "\n".join(line[:width] for line in lines[:height])


def query_snapshot(client, events, *, journal_path=None):
    rows = lifecycle_rows(client, events, journal_path=journal_path)
    for row in rows:
        row["reasons"] = attention_reasons(row)
    return build_snapshot(ready_work(client), rows)


def _cmd(args, log):
    """Interactive read-only command.  No key invokes an owner operation."""
    from .coordination import configured
    coordinator = configured(args.repo)
    if coordinator is None:
        print(f"{args.repo}: Vuoro coordination is not configured")
        return 1
    no_color = args.no_color or bool(os.environ.get("NO_COLOR"))
    if args.plain:
        snapshot = query_snapshot(coordinator.client, log.read(), journal_path=coordinator.path)
        print(render_plain_table(snapshot, args.view.title(), args.filter))
        return 0
    def run(screen):
        screen.keypad(True)
        snapshot = query_snapshot(coordinator.client, log.read(), journal_path=coordinator.path)
        state, refreshed = initial_state(snapshot, args.view.title(), args.filter), time.monotonic()
        while True:
            snapshot, view, filter_text = state["snapshot"], state["view"], state["filter"]
            rows, selected = view_rows(snapshot, view, filter_text), state["selected"]
            screen.erase()
            for y, line in enumerate(render_screen(snapshot, view, width=screen.getmaxyx()[1], height=screen.getmaxyx()[0], selected=selected or 0, filter_text=filter_text, color=not no_color, detail=state["detail"], help=state["help"], filtering=state["filtering"], filter_draft=state["filter_draft"]).splitlines()):
                try: screen.addnstr(y, 0, line, max(0, screen.getmaxyx()[1] - 1))
                except curses.error: pass
            screen.refresh()
            screen.timeout(max(0, int((args.refresh - (time.monotonic() - refreshed)) * 1000)))
            key = screen.getch()
            if key == -1 or (key == ord("r") and not state["filtering"]):
                snapshot = query_snapshot(coordinator.client, log.read(), journal_path=coordinator.path)
                state = handle_key(state, "refresh", snapshot=snapshot)
                refreshed = time.monotonic()
            else:
                state = handle_key(state, key)
                if state.get("quit"): return
    curses.wrapper(run)
    return 0


def register(sub):
    parser = sub.add_parser("tui", help="read-only Ready, Active and Verification operator TUI")
    parser.add_argument("--repo", required=True, help="configured owner repository")
    parser.add_argument("--view", choices=("ready", "active", "verification"), default="ready")
    parser.add_argument("--filter", default="", help="initial text filter")
    parser.add_argument("--plain", action="store_true", help="print the same query snapshot as the TUI")
    parser.add_argument("--no-color", action="store_true", help="disable terminal color")
    parser.add_argument("--refresh", type=float, default=15.0, help="refresh interval in seconds (default: 15)")
    return {"tui": _cmd}
