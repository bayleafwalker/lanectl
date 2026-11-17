"""Read-only operator TUI for lifecycle snapshots.

The view-model functions in this module have no terminal or owner I/O.  The
small curses adapter below them only obtains a new snapshot and renders it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import argparse
import curses
import json
import os
import sys
import textwrap
from queue import Empty, Queue
from threading import Thread
import time

from .render import CliError
from .vocab import SYMBOLS, classify, mark
from .lifecycle import (READS, attention_reasons, lifecycle_rows, local_facts,
                        ready_work, release_work_ids)

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
    value = _facts(row).get("work.public.item-v1", {}).get("value", {})
    item = value.get("item") if isinstance(value, dict) else None
    if isinstance(item, dict):
        return "blocked" if item.get("blocked") is True else item.get("status", "unknown")
    return value.get("state", "unknown") if isinstance(value, dict) else "unknown"


def _has_events(row, name):
    return bool(_facts(row).get(name, {}).get("value", []))


def build_snapshot(ready, rows, *, observed_at=None):
    """Build a coherent display input from lifecycle query results.

    ``ready`` and ``rows`` retain the source facts unchanged, making the
    detail pane auditable rather than a second lifecycle ledger.
    """
    return {"ready": ready, "rows": list(rows),
            "observed_at": observed_at or _stamp(datetime.now(timezone.utc))}


def _stamp(now):
    return now.replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def _owner_failure(snapshot):
    """Return an owner-read failure reason embedded by lifecycle readers.

    Lifecycle intentionally turns refused reads into unknown facts.  They are
    useful row-level evidence, but are not a successful owner refresh.  Missing
    optional identifiers are the one expected unknown and do not mean the
    owner is offline.
    """
    ready = snapshot.get("ready", {})
    if ready.get("state") != "observed":
        return ready.get("reason", "owner list unavailable")
    for row in snapshot.get("rows", []):
        for name in READS:
            fact = row.get("facts", {}).get(name, {})
            if fact.get("state") == "unknown" and fact.get("reason") != "no item identifier available" and fact.get("reason") != "no run identifier available":
                return fact.get("reason", f"owner read unavailable: {name}")
    return None


def _cached_owner_snapshot(previous, events, now):
    """Project new local data while retaining auditable last-good owner facts."""
    old = previous.get("snapshot", {})
    cached = {_identity(row): row for row in old.get("rows", [])}
    rows = _event_rows(events, now)
    for row in rows:
        prior = cached.get(_identity(row))
        if prior:
            row["work_id"] = prior.get("work_id")
            for name in READS:
                if name in prior.get("facts", {}):
                    row["facts"][name] = dict(prior["facts"][name])
            row["reasons"] = list(prior.get("reasons", []))
    # A row that no longer has a local claim is still a useful cached inspection.
    known = {_identity(row) for row in rows}
    rows.extend(row for identity, row in cached.items() if identity not in known)
    snapshot = build_snapshot(old.get("ready", {"state": "unknown", "source": "owner"}), rows,
                              observed_at=_stamp(now))
    snapshot["sources"] = dict(old.get("sources", {}))
    return snapshot


def _apply_owner_result(state, outcome, *, now, random_value, stale_after_s,
                        backoff_base_s, backoff_cap_s):
    """Apply an owner worker completion to serializable refresh state."""
    result = dict(state)
    previous = result.get("snapshot", {})
    owner_status = dict(previous.get("sources", {}).get("owner", {}))
    try:
        if isinstance(outcome, Exception):
            raise outcome
        failure = _owner_failure(outcome)
        if failure:
            raise RuntimeError(failure)
        snapshot = outcome
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
    # A worker may have completed against an earlier event checkpoint.  Keep
    # subsequently read local rows without pretending they have owner facts.
    if snapshot is not previous:
        staged = dict(result, snapshot=snapshot)
        snapshot = _cached_owner_snapshot(staged, result.get("events", []), now)
    age = _age(owner_status.get("observed_at"), now)
    if owner_status.get("state") in ("fresh", "offline") and age is not None and age > stale_after_s:
        owner_status["state"] = "stale"
    snapshot["sources"] = {**snapshot.get("sources", {}), "owner": owner_status}
    snapshot["actions_allowed"] = owner_status.get("state") == "fresh"
    result["snapshot"] = snapshot
    return result


def refresh_state(state, event_reader, owner_reader=None, *, now=None, random_value=None,
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
        # Readers are cursor based: incoming is strictly after checkpoint.
        # This preserves repeated event content as distinct append-only records.
        result["events"] = [*result.get("events", []), *incoming]
        result["event_checkpoint"] = checkpoint
        event_status["checkpoint"] = checkpoint
    except Exception as exc:  # source failure is data for this read-only UI
        event_status = dict(previous.get("sources", {}).get("events", event_status))
        event_status.update(state="offline", reason=str(exc))
    due = result.get("next_owner_attempt_at") is None or now >= result["next_owner_attempt_at"]
    owner_status = dict(previous.get("sources", {}).get("owner", {}))
    if due and owner_reader is not None:
        try:
            outcome = owner_reader(result.get("events", []), result.get("owner_revision"))
        except Exception as exc:
            outcome = exc
        result = _apply_owner_result(result, outcome, now=now, random_value=random_value,
                                     stale_after_s=stale_after_s, backoff_base_s=backoff_base_s,
                                     backoff_cap_s=backoff_cap_s)
        snapshot = result["snapshot"]
        owner_status = snapshot["sources"]["owner"]
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


class OwnerRefreshWorker:
    """One non-blocking owner read; completion is applied by the UI thread."""
    def __init__(self, reader, events, revision, *, clock=time.monotonic):
        self._results = Queue()
        self.started_at = clock()
        def run():
            try:
                self._results.put((reader(events, revision), None))
            except Exception as exc:
                self._results.put((None, exc))
        self._thread = Thread(target=run, daemon=True)
        self._thread.start()

    def poll(self):
        try:
            return self._results.get_nowait()
        except Empty:
            return None


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
    return f"{event_part} · {owner_part} · {capability}"


def _ago(seconds):
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m"


def _ready_key(item):
    """Owner list entries may be a string id or an object with work_id/id."""
    if isinstance(item, dict):
        return item.get("work_id", item.get("id"))
    return item


def view_rows(snapshot, view, filter_text=""):
    """Return normalized rows for a view, preserving owner order for Ready."""
    all_rows = snapshot.get("rows", [])
    by_item, by_work = {}, {}
    for row in all_rows:
        by_item.setdefault(_text(row.get("item_id")), row)
        if row.get("work_id") is not None:
            by_work.setdefault(_text(row.get("work_id")), row)
    if view == READY:
        items = snapshot.get("ready", {}).get("value", {}).get("items", [])
        rows = []
        for item in items:
            key = _ready_key(item)
            match = by_work.get(_text(key)) if isinstance(item, dict) else by_item.get(_text(key))
            if match is None:
                match = by_item.get(_text(key), by_work.get(_text(key)))
            rows.append(match or {"item_id": key, "work_id": key if isinstance(item, dict) else None,
                                  "attempt_id": None, "facts": {}, "reasons": []})
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
            "filter_draft": filter_text, "scroll": 0}


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


_DOWN = (curses.KEY_DOWN, ord("j"), "down", "j")
_UP = (curses.KEY_UP, ord("k"), "up", "k")
_PGDN = (curses.KEY_NPAGE, ord(" "), " ", "pgdn")
_PGUP = (curses.KEY_PPAGE, ord("b"), "b", "pgup")
_TOP = (curses.KEY_HOME, ord("g"), "g", "home")
_BOTTOM = (curses.KEY_END, ord("G"), "G", "end")


def _overlay_open(state):
    return bool(state.get("help")) or state.get("detail") is not None


def _filter_line_shown(state):
    return bool(state.get("filtering") or state.get("filter"))


def _body_height(height, filter_shown):
    """Rows between the header lines and the footer (tabs, status, [filter], footer)."""
    return max(1, height - 3 - (1 if filter_shown else 0))


def handle_key(state, key, *, snapshot=None, height=24, width=80):
    """Pure TUI state transition. ``snapshot`` supplies a refresh result.

    ``height`` and ``width`` size the viewport so scrolling can be bounded.
    """
    state = dict(state)
    state.setdefault("scroll", 0)
    rows = view_rows(state["snapshot"], state["view"], state["filter"])
    if key in ("refresh", "owner_result"):
        if snapshot is not None:
            state["snapshot"] = snapshot
        return _reconcile(state, previous_rows=rows)
    if state.get("filtering"):
        if key in (10, 13, "enter"):
            state["filter"] = state.get("filter_draft", "").strip()
            state["filtering"] = False
            state["detail"] = None
            state["scroll"] = 0
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
    overlay = _overlay_open(state)
    if key in (ord("q"), 27, "q", "esc"):
        if overlay:
            state.update(detail=None, help=False, scroll=0)
        else:
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
        state.update(view=VIEWS[index], selected=0, selection=None, detail=None, help=False,
                     scroll=0)
        return _reconcile(state)
    elif overlay and (key in _DOWN or key in _UP or key in _PGDN or key in _PGUP
                      or key in _TOP or key in _BOTTOM):
        _, lines = overlay_lines(state["snapshot"], state["view"], state["filter"],
                                 state["detail"], state["help"], width=width)
        page = max(1, _body_height(height, _filter_line_shown(state)) - 1)
        top = max(0, len(lines) - page)
        move = (1 if key in _DOWN else -1 if key in _UP else page if key in _PGDN
                else -page if key in _PGUP else None)
        state["scroll"] = (0 if key in _TOP else top if key in _BOTTOM
                           else max(0, min(top, state["scroll"] + move)))
    elif not overlay and rows and (key in _DOWN or key in _UP or key in _PGDN or key in _PGUP
                                   or key in _TOP or key in _BOTTOM):
        page = max(1, _body_height(height, _filter_line_shown(state)) // (2 if width < 80 else 1))
        current = state.get("selected") or 0
        target = (current + 1 if key in _DOWN else current - 1 if key in _UP
                  else current + page if key in _PGDN else current - page if key in _PGUP
                  else 0 if key in _TOP else len(rows) - 1)
        state["selected"] = max(0, min(len(rows) - 1, target))
        state["selection"] = _identity(rows[state["selected"]])
    elif key in (10, 13, "enter") and rows and not overlay:
        state.update(detail=(state["selection"], "detail"), help=False, scroll=0)
    elif key in (ord("e"), "e") and rows:
        state.update(detail=(state["selection"], "evidence"), help=False, scroll=0)
    elif key in (ord("s"), "s") and rows:
        state.update(detail=(state["selection"], "sources"), help=False, scroll=0)
    elif key in (ord("?"), "?"):
        state.update(help=True, detail=None, scroll=0)
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
    state = mark(_state(row))
    if view == READY:
        return (_text(row.get("item_id")), _text(row.get("attempt_id")), state, codes)
    if view == ACTIVE:
        return (_text(row.get("item_id")), _text(row.get("attempt_id")), state, _text(lease_value), codes)
    evidence = facts.get("work.evidence.tail-v1", {}).get("state", "local")
    return (_text(row.get("item_id")), _text(row.get("attempt_id")), state, evidence, codes)


def _clip(value, size):
    value = _text(value)
    return value if len(value) <= size else value[:max(0, size - 1)] + "…"


def _widths(table, width, marker=2):
    """Column widths: content-sized, the last (reasons) column takes the rest."""
    gap, count = 2, len(table[0])
    widths = [min(max(len(line[i]) for line in table), 30) for i in range(count - 1)]
    last = lambda: width - marker - gap * (count - 1) - sum(widths)
    while last() < 12 and max(widths) > 8:
        widths[widths.index(max(widths))] -= 1
    return widths + [max(1, last())]


def render_plain_table(snapshot, view, filter_text=""):
    """Plain, no-color, aligned representation of exactly the displayed view query."""
    rows = view_rows(snapshot, view, filter_text)
    table = [_columns(view)] + [_cells(row, view) for row in rows]
    widths = [max(len(line[i]) for line in table) for i in range(len(table[0]))]
    lines = [source_status_line(snapshot)]
    lines.extend("  ".join(c.ljust(w) for c, w in zip(line, widths)).rstrip() for line in table)
    return "\n".join(lines)


def detail_lines(row, *, evidence_only=False):
    """Render provenance plus the shared safe-detail allowlist."""
    from .verification import safe_fact_details
    lines = []
    for name, fact in _facts(row).items():
        if evidence_only and "evidence" not in name:
            continue
        lines.append(f"{name}: {fact.get('state', 'unknown')} · source={fact.get('source', '-')} · rev={fact.get('revision', '-')} · observed={fact.get('observed_at', '-')}")
        if fact.get("state") == "observed":
            details = safe_fact_details(name, fact)
            if details:
                lines.append(f"  {json.dumps(details, sort_keys=True, default=str)}")
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
    """List fact provenance and explicit safe references only."""
    from .verification import _references
    lines = []
    references = []

    def collect(value):
        if isinstance(value, dict):
            for reference in _references(value):
                if reference not in references:
                    references.append(reference)
            for child in value.values():
                collect(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                collect(child)

    for name, fact in _facts(row).items():
        local = " · local-only" if name.startswith("local.") else ""
        lines.append(f"{name}: source={fact.get('source', '-')} · revision={fact.get('revision', '-')}{local}")
        collect(fact.get("value"))
    lines.extend(f"link: {reference}" for reference in sorted(references))
    return lines or ["No sources were available for this row."]


HELP_LINES = [
    "Keys",
    "1 Ready · 2 Active · 3 Verification",
    "j/↓ k/↑ move or scroll · PgDn/Space PgUp/b page · g/G first/last",
    "/ filter (Enter apply, Esc cancel) · Enter inspect · e evidence · s sources",
    "r refresh (owner is polled at most once per --refresh interval)",
    "? this help · Esc/q close, then quit",
    "",
    "States (symbol and word; color is never the only cue)",
    *(f"{SYMBOLS[kind]} {label}" for kind, label in
      (("needs", "needs you"), ("failed", "failed"), ("running", "running"),
       ("ok", "ok/done"), ("idle", "idle/queued"), ("unknown", "unknown/stale"))),
]


def overlay_lines(snapshot, view, filter_text, detail, help, *, width=80):
    """``(title, wrapped lines)`` for the help or detail overlay, else ``None``."""
    if help:
        title, lines = "HELP", HELP_LINES
    elif detail is not None:
        rows = view_rows(snapshot, view, filter_text)
        identity, mode = detail if isinstance(detail, tuple) else (detail, "detail")
        index = _index_for(rows, identity) if isinstance(identity, tuple) else identity
        if index is None or index >= len(rows):
            title, lines = "DETAIL", ["item no longer in view"]
        else:
            row = rows[index]
            title = ("SOURCES " if mode == "sources" else "EVIDENCE " if mode in ("evidence", True)
                     else "DETAIL ") + _text(row.get("item_id"))
            if mode == "sources":
                lines = source_lines(row)
            elif mode in ("evidence", True):
                from .verification import evidence_bundle, render_bundle
                lines = render_bundle(evidence_bundle(row)).splitlines()
            else:
                lines = detail_lines(row)
    else:
        return None
    wrapped = []
    for line in lines:
        indent = " " * (len(line) - len(line.lstrip()))
        wrapped.extend(textwrap.wrap(line, width=max(8, width), subsequent_indent=indent + "  ",
                                     replace_whitespace=False) or [""])
    return title, wrapped


def _status_segments(snapshot, now, rows, selected):
    sources = snapshot.get("sources", {})
    if now is None:
        try:
            now = datetime.fromisoformat((snapshot.get("observed_at") or "").replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            now = None
    age = _age(snapshot.get("observed_at"), now) if now else None
    segs = [(f"updated {_ago(age)} ago" if age is not None else "updated ?", "")]
    for label in ("owner", "events"):
        source = sources.get(label, {})
        state = source.get("state", "unknown")
        text = f" · {label} {mark(state)}"
        if label == "owner" and source.get("next_attempt_at"):
            wait = (datetime.fromisoformat(source["next_attempt_at"].replace("Z", "+00:00")) - now).total_seconds() if now else None
            text += f" retry {_ago(wait)}" if wait is not None else ""
        segs.append((text, classify(state)))
    count = len(rows)
    segs.append((f" · row {selected + 1}/{count}" if count and selected is not None else f" · {count} rows", ""))
    if not snapshot.get("actions_allowed", True):
        segs.append((" · read-only, owner not fresh", "needs"))
    return segs


_FOOTERS = ("j/k move · Enter inspect · / filter · ? keys · q quit", "j/k · Enter · / · ? keys · q quit",
            "? keys · q quit", "? · q")
_OVERLAY_FOOTERS = ("j/k scroll · PgUp/PgDn · g/G · Esc back · ? keys · q quit", "j/k PgUp/PgDn · Esc back",
                    "Esc back · q quit", "Esc")


def _footer(width, overlay):
    options = _OVERLAY_FOOTERS if overlay else _FOOTERS
    return next((text for text in options if len(text) <= width), options[-1])


def _row_lines(rows, view, selected, width, count):
    """Visible list lines (wide table or stacked 2-line rows) scrolled to the selection."""
    cells = [_cells(row, view) for row in rows]
    stacked = width < 80
    per = 2 if stacked else 1
    head = 0 if stacked else 1
    window = max(1, (count - head) // per)
    first = max(0, min(selected - window + 1, len(rows) - window)) if rows else 0
    lines = []
    if not stacked:
        widths = _widths([_columns(view)] + cells, width)
        lines.append([("  " + "  ".join(c.ljust(w) for c, w in zip(_columns(view), widths)), "dim")])
    for index in range(first, min(len(rows), first + window)):
        cell, marker = cells[index], "> " if index == selected else "  "
        role = classify(_state(rows[index]))
        bold = "sel" if index == selected else ""
        if stacked:
            lines.append([(marker + f"{cell[0]} {cell[1]}", bold)])
            lines.append([("    ", ""), (cell[2], role), ("  " + " ".join(cell[3:]), "dim")])
        else:
            segs = [(marker, bold)]
            for i, (value, w) in enumerate(zip(cell, widths)):
                segs.append((_clip(value, w).ljust(w) + ("  " if i < len(cell) - 1 else ""),
                             role if i == 2 else bold if i == 0 else ""))
            lines.append(segs)
    return lines


def render_frame(snapshot, view, *, width, height, selected=0, filter_text="", detail=None,
                 help=False, filtering=False, filter_draft="", scroll=0, now=None):
    """Lines of ``(text, role)`` segments; roles map to curses attributes only."""
    width, height = max(1, width), max(1, height)
    rows = view_rows(snapshot, view, filter_text)
    tabs = "  ".join(f"[{i + 1} {name}]" if name == view else f" {i + 1} {name} "
                     for i, name in enumerate(VIEWS))
    lines = [[(tabs + ("  read-only" if len(tabs) + 11 <= width else ""), "head")],
             _status_segments(snapshot, now, rows, selected if rows else None)]
    filter_shown = filtering or bool(filter_text)
    if filtering:
        lines.append([("filter> " + filter_draft + "▏  Enter apply · Esc cancel", "sel")])
    elif filter_text:
        lines.append([(f"filter: {filter_text}", "dim")])
    body = _body_height(height, filter_shown)
    overlay = overlay_lines(snapshot, view, filter_text, detail, help, width=width)
    if overlay:
        title, wrapped = overlay
        room = max(1, body - 1)
        top = max(0, min(scroll, len(wrapped) - room))
        more = f" · {top + 1}-{min(len(wrapped), top + room)}/{len(wrapped)}" if len(wrapped) > room else ""
        lines.append([(title + more, "head")])
        lines.extend([(text, "")] for text in wrapped[top:top + room])
    else:
        room = body
        if snapshot.get("selection_missing") and not filtering:
            item, attempt = snapshot["selection_missing"]
            lines.append([(f"NO MATCHING ROW item={_text(item)} attempt={_text(attempt)}", "needs")])
            room -= 1
        if rows:
            lines.extend(_row_lines(rows, view, selected, width, room))
        else:
            lines.append([("no rows" + (" match the filter (/ to change)" if filter_text else ""), "dim")])
    lines = lines[:height - 1]
    lines.extend([[("", "")]] * (height - 1 - len(lines)))
    lines.append([(_footer(width, overlay is not None), "dim")])
    clipped = []
    for line in lines:
        left, out = width, []
        for text, role in line:
            if left <= 0:
                break
            out.append((text[:left], role))
            left -= len(text)
        clipped.append(out)
    return clipped


def render_screen(snapshot, view, *, width, height, selected=0, filter_text="", color=False,
                  detail=None, help=False, filtering=False, filter_draft="", scroll=0, now=None):
    """Render a text frame of exactly ``height`` lines, each at most ``width`` wide.

    ``color`` is accepted for the caller's convenience: this text never carries
    escape codes, the curses adapter colours the segments from ``render_frame``.
    """
    del color
    frame = render_frame(snapshot, view, width=width, height=height, selected=selected,
                         filter_text=filter_text, detail=detail, help=help, filtering=filtering,
                         filter_draft=filter_draft, scroll=scroll, now=now)
    return "\n".join("".join(text for text, _ in line).rstrip() for line in frame)


def query_snapshot(client, events, *, journal_path=None, work_ids=None,
                   item=None, attempt=None):
    if work_ids is None:
        try:
            from .config import load_releases
            work_ids = release_work_ids(load_releases())
        except (OSError, ValueError):
            work_ids = None
    rows = lifecycle_rows(client, events, item_id=item, attempt_id=attempt,
                          journal_path=journal_path, work_ids=work_ids)
    for row in rows:
        row["reasons"] = attention_reasons(row)
    if item is not None or attempt is not None:
        # A permalink selects an exact identity; an unknown selection is empty
        # rather than an invitation to fall through to another lifecycle.
        ready = {"state": "observed", "source": "selection", "revision": None,
                 "value": {"items": [
                     row.get("item_id") if row.get("work_id") is None else
                     {"work_id": row.get("work_id"), "item_id": row.get("item_id")}
                     for row in rows]}}
        snapshot = build_snapshot(ready, rows)
        snapshot["selection"] = (item, attempt)
        if not rows:
            snapshot["selection_missing"] = (item, attempt)
        return snapshot
    return build_snapshot(ready_work(client), rows)


class OwnerPoller:
    """Starts owner reads no more often than ``interval`` seconds (and not before backoff).

    The UI loop wakes far more often than the interval to redraw and read keys;
    this keeps that from becoming owner traffic.
    """
    def __init__(self, reader, interval, *, clock=time.monotonic, worker=OwnerRefreshWorker):
        self.reader, self.interval, self.clock, self.worker_type = reader, interval, clock, worker
        self.worker, self.last_started = None, None

    def due(self, refresh, now):
        if self.worker is not None:
            return False
        if self.last_started is not None and self.clock() - self.last_started < self.interval:
            return False
        retry = refresh.get("next_owner_attempt_at")
        return retry is None or now >= retry

    def step(self, refresh, now):
        """Start a read if due and apply a finished one; returns ``(refresh, changed)``."""
        if self.due(refresh, now):
            self.worker = self.worker_type(self.reader, list(refresh.get("events", [])),
                                           refresh.get("owner_revision"))
            self.last_started = self.clock()
        completed = self.worker.poll() if self.worker is not None else None
        if completed is None:
            return refresh, False
        outcome, error = completed
        self.worker = None
        return _apply_owner_result(refresh, error or outcome, now=now,
                                   random_value=__import__("random").random, stale_after_s=60,
                                   backoff_base_s=2, backoff_cap_s=60), True


def not_configured_message(repo):
    """What happened, why, the exact fix and the docs, for an unconfigured owner."""
    return (f"error: {repo}: Vuoro coordination is not configured\n"
            f"  why: governance/vuoro.toml has no [repos.{repo}] table (or the file is missing)\n"
            f"  fix: add [repos.{repo}] with endpoint, repo_id, expected_environment and one of "
            "token_env or credential_name to governance/vuoro.toml\n"
            "  docs: docs/architecture/vuoro-coordination.md")


def _interactive():
    return sys.stdin.isatty() and sys.stdout.isatty() and os.environ.get("TERM", "") not in ("", "dumb")


def _use_color(no_color):
    if no_color or os.environ.get("NO_COLOR") or not curses.has_colors():
        return False
    return True


_PAIRS = {"ok": curses.COLOR_GREEN, "needs": curses.COLOR_YELLOW, "failed": curses.COLOR_RED,
          "running": curses.COLOR_CYAN, "idle": curses.COLOR_WHITE, "unknown": curses.COLOR_MAGENTA}


def _attributes(color):
    """Map frame roles to curses attributes; bold/dim carry emphasis without color."""
    attrs = {"": 0, "head": curses.A_BOLD, "sel": curses.A_BOLD, "dim": curses.A_DIM}
    if color:
        try:
            curses.use_default_colors()
        except curses.error:   # terminal without default-colour support: draw without colour
            color = False
    if color:
        for number, (role, fg) in enumerate(_PAIRS.items(), 1):
            curses.init_pair(number, fg, -1)
            attrs[role] = curses.color_pair(number) | (curses.A_BOLD if role in ("needs", "failed") else 0)
    else:
        attrs.update({role: curses.A_BOLD if role in ("needs", "failed") else 0 for role in _PAIRS})
    return attrs


def _cmd(args, log):
    """Interactive read-only command. No key mutates owner state."""
    from .coordination import configured
    if not args.plain and not _interactive():
        from . import cli, status   # contract section 8: off a TTY the TUI prints `status`
        cli._check_home()
        return status._cmd(argparse.Namespace(all=False, json=False), log)
    if not args.repo:
        raise CliError("tui needs --repo", why="the TUI reads lifecycle facts from the owner",
                       fix="lanectl tui --repo <repo>", code=2, slug="usage")
    coordinator = configured(args.repo)
    if coordinator is None:
        print(not_configured_message(args.repo), file=sys.stderr)
        return 1
    no_color = args.no_color or getattr(args, "tui_no_color", False) or bool(os.environ.get("NO_COLOR"))
    from .config import load_releases
    work_ids = release_work_ids(load_releases())
    def event_reader(checkpoint):
        offset = checkpoint or 0
        events = log.read(after=offset)
        return events, offset + len(events)
    def owner_reader(events, revision):
        # ``revision`` is retained by refresh_state as the resume point.  The
        # currently advertised owner reads are snapshots, so no unsupported
        # revision argument is manufactured for the owner.
        del revision
        return query_snapshot(coordinator.client, events, journal_path=coordinator.path,
                              work_ids=work_ids, item=args.item, attempt=args.attempt)
    if args.plain:
        refreshed = refresh_state(initial_refresh_state(), event_reader, owner_reader)
        snapshot = refreshed["snapshot"]
        if (args.item is not None or args.attempt is not None) and not snapshot.get("rows"):
            print(f"no matching lifecycle row for item={args.item} attempt={args.attempt}")
            return 1
        print(render_plain_table(snapshot, args.view.title(), args.filter))
        return 0
    def run(screen):
        screen.keypad(True)
        attrs = _attributes(_use_color(no_color))
        refresh = refresh_state(initial_refresh_state(), event_reader)
        state, refreshed = initial_state(refresh["snapshot"], args.view.title(), args.filter), time.monotonic()
        poller = OwnerPoller(owner_reader, args.refresh)
        while True:
            height, width = screen.getmaxyx()
            screen.erase()
            frame = render_frame(state["snapshot"], state["view"], width=width - 1, height=height,
                                 selected=state["selected"] or 0, filter_text=state["filter"],
                                 detail=state["detail"], help=state["help"],
                                 filtering=state["filtering"], filter_draft=state["filter_draft"],
                                 scroll=state.get("scroll", 0), now=datetime.now(timezone.utc))
            for y, line in enumerate(frame):
                x = 0
                for text, role in line:
                    try: screen.addstr(y, x, text, attrs.get(role, 0))
                    except curses.error: pass
                    x += len(text)
            screen.refresh()
            refresh, changed = poller.step(refresh, datetime.now(timezone.utc))
            if changed:
                state = handle_key(state, "owner_result", snapshot=refresh["snapshot"])
            screen.timeout(500)
            key = screen.getch()
            # Local events are re-read each --refresh interval (even while keys arrive) or on r.
            manual = key == ord("r") and not state["filtering"]
            if manual or time.monotonic() - refreshed >= args.refresh:
                refresh = refresh_state(refresh, event_reader)
                state = handle_key(state, "refresh", snapshot=refresh["snapshot"])
                refreshed = time.monotonic()
            if key != -1 and not manual:
                state = handle_key(state, key, height=height, width=width - 1)
                if state.get("quit"): return
    curses.wrapper(run)
    return 0


def _refresh_seconds(text):
    value = float(text)
    if not value >= 1:
        raise argparse.ArgumentTypeError("must be at least 1 second (continuous owner reads are refused)")
    return value


def register(sub):
    parser = sub.add_parser("tui", help="read-only Ready, Active and Verification operator TUI")
    parser.add_argument("--repo", help="configured owner repository (required on a terminal)")
    parser.add_argument("--view", choices=("ready", "active", "verification"), default="ready")
    parser.add_argument("--filter", default="", help="initial text filter")
    parser.add_argument("--item", help="exact local release id to jump to")
    parser.add_argument("--attempt", help="exact attempt id to jump to")
    parser.add_argument("--plain", action="store_true", help="print the same query snapshot as the TUI")
    # Own dest: the subparser's default would otherwise overwrite the root `--no-color`.
    parser.add_argument("--no-color", dest="tui_no_color", action="store_true", help="disable terminal color")
    parser.add_argument("--refresh", type=_refresh_seconds, default=15.0,
                        help="refresh interval in seconds, at least 1 (default: 15)")
    return {"tui": _cmd}
