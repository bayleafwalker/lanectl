"""The release a planner or integrator session is working on, for attribution.

A session names its release once with ``lanectl focus <release-id>`` and the
interactive Stop hook stamps that id on every ``usage.recorded`` event it
writes, so cost per landed item includes operator time (ladder rung 4; ADR 0001
stop condition).  A stale focus would bill the wrong release, so anything older
than ``MAX_AGE`` is ignored as if it were absent.
"""
from __future__ import annotations

import json
import os
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


def focus_path() -> Path:
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


def set_focus(release_id: str, role: str = "planner") -> dict:
    """Record ``release_id`` as the focus for ``role`` (atomic write)."""
    now = datetime.now(timezone.utc)
    entry = {"release_id": release_id, "role": role, "set_at": now.strftime(STAMP)}
    path = focus_path()
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


def clear_focus() -> None:
    """Remove the focus file; clearing an absent focus is not an error."""
    try:
        focus_path().unlink()
    except FileNotFoundError:
        pass


def current_focus() -> dict | None:
    """The live focus, or None when absent, unreadable or older than ``MAX_AGE``."""
    try:
        raw = json.loads(focus_path().read_text(encoding="utf-8"))
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


def register(sub) -> dict:
    p = sub.add_parser("focus", help="attribute interactive usage to a release")
    p.add_argument("release_id", nargs="?", help="release id under backlog/ (omit to show)")
    p.add_argument("--role", choices=ROLES, default="planner")
    p.add_argument("--clear", action="store_true", help="drop the current focus")
    return {"focus": _cmd}


def _cmd(args, log: EventLog) -> int:
    if args.clear:
        clear_focus()
        print("focus cleared")
        return 0
    if args.release_id is None:
        focus = current_focus()
        print(f"focus: {focus['release_id']} ({focus['role']})" if focus else "no focus")
        return 0
    release_dir = home() / "backlog" / args.release_id
    try:
        load_release(release_dir)
    except (OSError, ValueError) as exc:
        print(f"focus: {args.release_id!r}: {exc}", file=sys.stderr)
        return 2
    set_focus(args.release_id, args.role)
    print(f"focus: {args.release_id} ({args.role})")
    return 0
