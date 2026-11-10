"""The release a planner or integrator session is working on, for attribution.

A session names its release once with ``lanectl focus <release-id>`` and the
interactive Stop hook stamps that id on every ``usage.recorded`` event it
writes, so cost per landed item includes operator time (ladder rung 4; ADR 0001
stop condition).  A stale focus would bill the wrong release, so anything older
than ``MAX_AGE`` is ignored as if it were absent.

Focus is per Claude session: when a ``session_id`` is given the focus lives in
``focus/<session_id>.json`` under the state directory, otherwise in the
machine-wide ``focus.json``.  A session id is only ever used as a path when it
matches ``[A-Za-z0-9_-]+``; anything else is treated as absent from the
per-session store.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import home, load_release
from .events import EventLog, state_dir

ROLES = ("planner", "integrator")
FOCUS_FILE = "focus.json"
MAX_AGE = timedelta(hours=12)
STAMP = "%Y-%m-%dT%H:%M:%SZ"
_SESSION_ID = re.compile(r"[A-Za-z0-9_-]+\Z")


def _session_path(session_id) -> Path | None:
    """The per-session focus file, or None when ``session_id`` is absent/unsafe."""
    if isinstance(session_id, str) and session_id and _SESSION_ID.fullmatch(session_id):
        return state_dir() / "focus" / f"{session_id}.json"
    return None


def _target(session_id) -> Path | None:
    """Focus file for ``session_id``: machine-wide when None, else per-session.

    Returns None for an unsafe session id, which is treated as absent from the
    per-session store and never used as a path.
    """
    if session_id is None:
        return focus_path()
    return _session_path(session_id)


def focus_path() -> Path:
    """The machine-wide focus file."""
    return state_dir() / FOCUS_FILE


def _parse(value) -> datetime | None:
    """Parse an ISO-8601 UTC stamp, or None when it is not one."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _read(path: Path) -> dict | None:
    """The live focus at ``path``, or None when absent, unreadable or stale."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    release_id = raw.get("release_id")
    role = raw.get("role")
    if not isinstance(release_id, str) or not release_id.strip() or not isinstance(role, str):
        return None
    set_at = _parse(raw.get("set_at"))
    if set_at is None or datetime.now(timezone.utc) - set_at > MAX_AGE:
        return None
    return {"release_id": release_id, "role": role, "set_at": raw["set_at"]}


def set_focus(release_id: str, role: str = "planner", session_id=None) -> dict:
    """Record ``release_id`` as the focus for ``role`` (atomic write).

    With ``session_id`` the focus is scoped to that Claude session; an unsafe
    session id is treated as absent and nothing is written.
    """
    now = datetime.now(timezone.utc)
    entry = {"release_id": release_id, "role": role, "set_at": now.strftime(STAMP)}
    path = _target(session_id)
    if path is None:
        return entry
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(entry, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return entry


def clear_focus(session_id=None) -> None:
    """Remove the focus file; clearing an absent focus is not an error."""
    path = _target(session_id)
    if path is None:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def current_focus(session_id=None) -> dict | None:
    """The live focus, or None when absent, unreadable or older than ``MAX_AGE``.

    With ``session_id``, reads that session's focus; an unsafe session id is
    treated as absent from the per-session store.
    """
    path = _target(session_id)
    if path is None:
        return None
    return _read(path)


def register(sub) -> dict:
    p = sub.add_parser("focus", help="attribute interactive usage to a release")
    p.add_argument("release_id", nargs="?", help="release id under backlog/ (omit to show)")
    p.add_argument("--role", choices=ROLES, default="planner")
    p.add_argument("--clear", action="store_true", help="drop the current focus")
    p.add_argument("--all-sessions", action="store_true",
                   help="set or clear the machine-wide focus (every session)")
    return {"focus": _cmd}


_NO_SESSION = "focus: no CLAUDE_CODE_SESSION_ID; pass --all-sessions to focus every session"


def _cmd(args, log: EventLog) -> int:
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip() or None
    if args.all_sessions:
        session_id = None

    if args.clear:
        if session_id is None and not args.all_sessions:
            print(_NO_SESSION)
            return 2
        clear_focus(session_id)
        print("focus cleared")
        return 0

    if args.release_id is None:
        focus = current_focus(session_id)
        if focus is None:
            print("no focus")
        elif session_id is None:
            print(f"focus: {focus['release_id']} ({focus['role']})")
        else:
            print(f"focus: {focus['release_id']} ({focus['role']}, this session)")
        return 0

    if session_id is None and not args.all_sessions:
        print(_NO_SESSION)
        return 2

    release_dir = home() / "backlog" / args.release_id
    try:
        load_release(release_dir)
    except (OSError, ValueError) as exc:
        print(f"focus: {args.release_id!r}: {exc}", file=sys.stderr)
        return 2
    set_focus(args.release_id, args.role, session_id)
    if args.all_sessions:
        print(f"focus: {args.release_id} ({args.role}, all sessions)")
    else:
        print(f"focus: {args.release_id} ({args.role}, this session)")
    return 0
