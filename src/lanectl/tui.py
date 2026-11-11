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


def render_screen(snapshot, view, *, width, height, selected=0, filter_text="", color=False, detail=None):
    """Render an 80x24-safe text frame; color is deliberately presentation-only."""
    del color  # state is always conveyed by words and markers.
    width, height = max(1, width), max(1, height)
    rows = view_rows(snapshot, view, filter_text)
    stamp = snapshot.get("observed_at", "unknown")
    lines = [f"{view} (read-only) · observed {stamp}", f"FILTER {filter_text or '-'} · {len(rows)} rows",
             _fit(_columns(view), width)]
    if detail is not None and rows:
        detail_index, evidence_only = detail if isinstance(detail, tuple) else (detail, False)
        lines.append(("EVIDENCE " if evidence_only else "DETAIL ") + _text(rows[detail_index].get("item_id")))
        lines.extend(detail_lines(rows[detail_index], evidence_only=evidence_only))
    else:
        for index, row in enumerate(rows):
            lines.append(_fit(_cells(row, view), width, "> " if index == selected else "  "))
    footer = "1 Ready  2 Active  3 Verification  / filter  r refresh  Enter inspect  e evidence  s sources  ? help  q quit"
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
        view, filter_text, selected, detail = args.view.title(), args.filter, 0, None
        snapshot, old_rows, refreshed = query_snapshot(coordinator.client, log.read(), journal_path=coordinator.path), [], time.monotonic()
        while True:
            rows = view_rows(snapshot, view, filter_text)
            selected = focus_index(old_rows, selected, rows)
            old_rows = rows
            screen.erase()
            for y, line in enumerate(render_screen(snapshot, view, width=screen.getmaxyx()[1], height=screen.getmaxyx()[0], selected=selected or 0, filter_text=filter_text, color=not no_color, detail=detail).splitlines()):
                try: screen.addnstr(y, 0, line, max(0, screen.getmaxyx()[1] - 1))
                except curses.error: pass
            screen.refresh()
            screen.timeout(max(0, int((args.refresh - (time.monotonic() - refreshed)) * 1000)))
            key = screen.getch()
            if key == -1 or key in (ord("r"),):
                snapshot = query_snapshot(coordinator.client, log.read(), journal_path=coordinator.path); refreshed = time.monotonic(); detail = None; continue
            if key in (ord("q"), 27): return
            if key in (ord("1"), ord("2"), ord("3")):
                view, selected, detail = VIEWS[key - ord("1")], 0, None; continue
            if key in (curses.KEY_DOWN, ord("j")) and rows: selected = min((selected or 0) + 1, len(rows) - 1)
            elif key in (curses.KEY_UP, ord("k")) and rows: selected = max((selected or 0) - 1, 0)
            elif key in (10, 13) and rows: detail = (selected, False)
            elif key == ord("e") and rows: detail = (selected, True)
            elif key == ord("s") and rows: detail = (selected, False)
            elif key == ord("?"):
                detail = None
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
