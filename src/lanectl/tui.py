"""Read-only operator TUI for lifecycle snapshots.

The view-model functions in this module have no terminal or owner I/O.  The
small curses adapter below them only obtains a new snapshot and renders it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import curses
import os
import time

from .lifecycle import READS, attention_reasons, lifecycle_rows, local_facts, ready_work

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


def _stamp(now):
    return now.isoformat().replace("+00:00", "Z")


def _age(stamp, now):
    try:
        return max(0, (now - datetime.fromisoformat(stamp.replace("Z", "+00:00"))).total_seconds())
    except (AttributeError, ValueError):
        return None


def initial_refresh_state():
    """Return the serializable state for independent event and owner refreshes."""
    return {"events": [], "event_checkpoint": None, "owner_revision": None,
            "owner_failures": 0, "next_owner_attempt_at": None,
            "snapshot": build_snapshot({"state": "unknown", "source": "owner", "reason": "not read"}, [])}


def _event_rows(events, now):
    rows = []
    for event in events:
        if event.get("type") != "item.claimed":
            continue
        attempt = event.get("data", {}).get("attempt_id")
        facts = local_facts(events, item_id=event.get("item_id"), attempt_id=attempt)
        for name in READS:
            facts[name] = {"state": "unknown", "source": name, "revision": None,
                           "observed_at": _stamp(now), "reason": "owner unavailable"}
        rows.append({"item_id": event.get("item_id"), "attempt_id": attempt, "facts": facts,
                     "reasons": []})
    return rows


def _unique_events(existing, incoming):
    """Accept a replayed checkpoint page without duplicating local projections."""
    import json
    result, seen = [], set()
    for event in [*existing, *incoming]:
        key = json.dumps(event, sort_keys=True, separators=(",", ":"), default=str)
        if key not in seen:
            seen.add(key)
            result.append(event)
    return result


def _cached_owner_snapshot(previous, events, now):
    """Project new local data while retaining auditable last-good owner facts."""
    old = previous.get("snapshot", {})
    cached = {_identity(row): row for row in old.get("rows", [])}
    rows = _event_rows(events, now)
    for row in rows:
        prior = cached.get(_identity(row))
        if prior:
            for name in READS:
                if name in prior.get("facts", {}):
                    row["facts"][name] = dict(prior["facts"][name])
            row["reasons"] = list(prior.get("reasons", []))
    # A row that no longer has a local claim is still a useful cached inspection.
    known = {_identity(row) for row in rows}
    rows.extend(row for identity, row in cached.items() if identity not in known)
    return build_snapshot(old.get("ready", {"state": "unknown", "source": "owner"}), rows,
                          observed_at=_stamp(now))


def refresh_state(state, event_reader, owner_reader, *, now=None, random_value=None,
                  stale_after_s=60, backoff_base_s=2, backoff_cap_s=60):
    """Refresh local events and owner facts independently.

    Both readers are injected. ``event_reader(checkpoint)`` returns
    ``(events, checkpoint)`` and ``owner_reader(events, revision)`` returns a
    normal TUI snapshot.  Errors become visible source state, never an empty
    owner result; last-good owner facts remain inspectable.
    """
    now = now or datetime.now(timezone.utc)
    random_value = random_value or __import__("random").random
    result = dict(state)
    previous = result.get("snapshot", {})
    event_status = {"state": "fresh", "checkpoint": result.get("event_checkpoint"), "observed_at": _stamp(now)}
    try:
        incoming, checkpoint = event_reader(result.get("event_checkpoint"))
        result["events"] = _unique_events(result.get("events", []), incoming)
        result["event_checkpoint"] = checkpoint
        event_status["checkpoint"] = checkpoint
    except Exception as exc:  # source failure is data for this read-only UI
        event_status = dict(previous.get("sources", {}).get("events", event_status))
        event_status.update(state="offline", reason=str(exc))
    due = result.get("next_owner_attempt_at") is None or now >= result["next_owner_attempt_at"]
    owner_status = dict(previous.get("sources", {}).get("owner", {}))
    if due:
        try:
            snapshot = owner_reader(result.get("events", []), result.get("owner_revision"))
            result["owner_revision"] = snapshot.get("ready", {}).get("revision")
            result["owner_failures"] = 0
            result["next_owner_attempt_at"] = None
            owner_status = {"state": "fresh", "observed_at": _stamp(now),
                            "revision": result["owner_revision"]}
        except Exception as exc:  # cached inspection deliberately survives outage
            result["owner_failures"] = result.get("owner_failures", 0) + 1
            raw = min(backoff_cap_s, backoff_base_s * (2 ** (result["owner_failures"] - 1)))
            delay = min(backoff_cap_s, raw * (1 + max(0, min(1, random_value())) / 2))
            result["next_owner_attempt_at"] = now + timedelta(seconds=delay)
            snapshot = _cached_owner_snapshot(result, result.get("events", []), now)
            owner_status.update(state="offline", reason=str(exc), failures=result["owner_failures"],
                                next_attempt_at=_stamp(result["next_owner_attempt_at"]))
    else:
        snapshot = _cached_owner_snapshot(result, result.get("events", []), now)
    age = _age(owner_status.get("observed_at"), now)
    if owner_status.get("state") == "fresh" and age is not None and age > stale_after_s:
        owner_status["state"] = "stale"
    # An outage past the freshness threshold is stale rather than merely offline.
    if owner_status.get("state") == "offline" and age is not None and age > stale_after_s:
        owner_status["state"] = "stale"
    event_age = _age(event_status.get("observed_at"), now)
    if event_status.get("state") == "offline" and event_age is not None and event_age > stale_after_s:
        event_status["state"] = "stale"
    snapshot["sources"] = {"events": event_status, "owner": owner_status}
    snapshot["actions_allowed"] = owner_status.get("state") == "fresh"
    result["snapshot"] = snapshot
    return result


def source_status_line(snapshot):
    """Textual source health shared by terminal and plain-table renderers."""
    sources = snapshot.get("sources", {})
    owner, events = sources.get("owner", {}), sources.get("events", {})
    owner_state = owner.get("state", "unknown").upper()
    now = snapshot.get("observed_at")
    try:
        display_now = datetime.fromisoformat(now.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        display_now = None
    owner_part = f"OWNER {owner_state}"
    if owner.get("observed_at"):
        owner_part += f" observed {owner['observed_at']}"
        owner_age = _age(owner["observed_at"], display_now) if display_now else None
        if owner_age is not None:
            owner_part += f" age {int(owner_age)}s"
    if owner.get("next_attempt_at"):
        owner_part += f" retry {owner['next_attempt_at']}"
    event_part = f"EVENTS {events.get('state', 'unknown').upper()}"
    if events.get("checkpoint") is not None:
        event_part += f" checkpoint {events['checkpoint']}"
    if events.get("observed_at"):
        event_age = _age(events["observed_at"], display_now) if display_now else None
        if event_age is not None:
            event_part += f" age {int(event_age)}s"
    capability = "actions allowed" if snapshot.get("actions_allowed", True) else "actions disabled"
    return f"{event_part} · OWNER {owner_state} {capability} · {owner_part}"


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
    lines = [source_status_line(snapshot), "  ".join(_columns(view))]
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
    lines = [f"{view} (read-only) · observed {stamp}", source_status_line(snapshot), f"FILTER {shown_filter or '-'} · {len(rows)} rows",
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
    def event_reader(checkpoint):
        events = log.read()
        return events, len(events)
    def owner_reader(events, revision):
        # ``revision`` is retained by refresh_state as the resume point.  The
        # currently advertised owner reads are snapshots, so no unsupported
        # revision argument is manufactured for the owner.
        del revision
        return query_snapshot(coordinator.client, events, journal_path=coordinator.path)
    if args.plain:
        refreshed = refresh_state(initial_refresh_state(), event_reader, owner_reader)
        print(render_plain_table(refreshed["snapshot"], args.view.title(), args.filter))
        return 0
    def run(screen):
        screen.keypad(True)
        refresh = refresh_state(initial_refresh_state(), event_reader, owner_reader)
        snapshot = refresh["snapshot"]
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
                refresh = refresh_state(refresh, event_reader, owner_reader)
                state = handle_key(state, "refresh", snapshot=refresh["snapshot"])
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
