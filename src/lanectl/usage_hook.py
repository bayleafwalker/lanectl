"""Record interactive Claude Code sessions' usage from the ``Stop`` hook.

Interactive sessions draw from the same subscription windows as lane workers,
so their usage has to reach the control plane too.  Claude Code invokes the
hook with a JSON payload on stdin::

    {"session_id": "...", "transcript_path": "/path/to/<session>.jsonl",
     "hook_event_name": "Stop"}

The transcript is an append-only JSONL stream in which every assistant turn
carries ``message.id``, ``message.model`` and ``message.usage``.  Streamed
turns may be repeated with the same id, so messages are deduplicated by id.

Interactive usage is attributed to the release a planner or integrator session
is working on: ``LANECTL_RELEASE`` wins, then ``lanectl focus``.  The role comes
from ``LANECTL_ROLE``, then the focus, and defaults to ``interactive``.

A per-session cursor (file offset plus the ids already seen) lives next to the
event log, under the state directory.  Each run only reads the bytes appended
since the previous run and records one ``usage.recorded`` event for the delta.
A truncated or replaced transcript is re-read from the start; the id set keeps
that safe.

A hook must never break the interactive session: every failure is swallowed
and turns into exit code 0 with nothing recorded.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

from .events import EventLog
from .focus import current_focus

PROVIDER = "anthropic"
SOURCE = "claude-code-interactive"
CURSOR_DIR = "usage-hook"
CHUNK = 1 << 20
#: Roles an interactive session can claim; anything else is just ``interactive``.
ROLES = ("planner", "integrator", "interactive")
DEFAULT_ROLE = "interactive"

# transcript usage key -> units key reported in the event
UNITS = {
    "input_tokens": "input_tokens",
    "output_tokens": "output_tokens",
    "cache_read_input_tokens": "cache_read_tokens",
    "cache_creation_input_tokens": "cache_write_tokens",
}


def _cursor_path(log: EventLog, session_id: str) -> Path:
    """Session cursor next to the log; hashed so any id is a safe file name."""
    digest = hashlib.sha256(session_id.encode("utf-8", "surrogatepass")).hexdigest()[:32]
    return Path(log.path).parent / CURSOR_DIR / f"{digest}.json"


def _load_cursor(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"offset": 0, "messages": []}
    if not isinstance(raw, dict):
        return {"offset": 0, "messages": []}
    offset = raw.get("offset")
    seen = raw.get("messages")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        offset = 0
    return {
        "offset": offset,
        "messages": [x for x in seen if isinstance(x, str)] if isinstance(seen, list) else [],
    }


def _save_cursor(path: Path, cursor: dict) -> None:
    """Write the cursor atomically so a crash never leaves a torn file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(cursor, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _lines(path: Path, offset: int):
    """Yield ``(line_bytes, end_offset)`` for complete lines from ``offset``."""
    try:
        size = path.stat().st_size
    except OSError:
        return
    if offset > size:           # truncated or replaced: start over; ids dedupe
        offset = 0
    with open(path, "rb") as stream:
        stream.seek(offset)
        position = offset
        pending = b""
        while True:
            chunk = stream.read(CHUNK)
            if not chunk:
                break
            pending += chunk
            while True:
                newline = pending.find(b"\n")
                if newline < 0:
                    break
                line, pending = pending[:newline], pending[newline + 1:]
                position += newline + 1
                yield line, position
        if pending.strip():
            # Consume a trailing line without a newline only if it is complete.
            try:
                json.loads(pending.decode("utf-8", "replace"))
            except ValueError:
                return
            position += len(pending)
            yield pending, position


def _assistant(line: bytes):
    """Return ``(message_id, model, usage)`` for an assistant line, else None."""
    try:
        obj = json.loads(line)
    except ValueError:
        return None
    if not isinstance(obj, dict) or obj.get("type") != "assistant":
        return None
    message = obj.get("message")
    if not isinstance(message, dict):
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    key = message.get("id") or obj.get("uuid")
    if not isinstance(key, str) or not key:
        return None
    model = message.get("model")
    return key, model if isinstance(model, str) else "", usage


def _count(usage: dict, key: str) -> int:
    value = usage.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value) if value > 0 else 0


def _collect(path: Path, cursor: dict):
    """Read the delta and return (units, models, message_count, new cursor)."""
    seen = set(cursor["messages"])
    totals = dict.fromkeys(UNITS.values(), 0)
    models: Counter = Counter()
    messages = 0
    offset = cursor["offset"]
    for line, end in _lines(path, offset):
        offset = end
        parsed = _assistant(line)
        if parsed is None:
            continue
        key, model, usage = parsed
        if key in seen:
            continue
        seen.add(key)
        messages += 1
        for source_key, unit_key in UNITS.items():
            totals[unit_key] += _count(usage, source_key)
        if model:
            models[model] += 1
    return totals, models, messages, {"offset": offset, "messages": sorted(seen)}


def _attribution() -> tuple[str | None, str]:
    """``(release_id, role)``: environment first, then the recorded focus."""
    release = os.environ.get("LANECTL_RELEASE", "").strip()
    role = os.environ.get("LANECTL_ROLE", "").strip()
    if not release or not role:
        try:
            focus = current_focus()
        except Exception:       # attribution must never break the hook
            focus = None
        if focus:
            release = release or focus["release_id"]
            role = role or focus["role"]
    return (release or None), (role if role in ROLES else DEFAULT_ROLE)


def handle_hook(stdin, log: EventLog) -> int:
    """Handle one Stop-hook invocation.  Always returns 0; never raises."""
    try:
        raw = stdin.read() if stdin is not None else ""
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        payload = json.loads(raw)

        if not isinstance(payload, dict):
            return 0
        session_id = payload.get("session_id")
        transcript = payload.get("transcript_path")
        if not isinstance(session_id, str) or not session_id.strip():
            return 0
        if not isinstance(transcript, str) or not transcript:
            return 0

        cursor_path = _cursor_path(log, session_id)
        cursor = _load_cursor(cursor_path)
        totals, models, messages, new_cursor = _collect(Path(transcript), cursor)

        if messages == 0:
            if new_cursor["offset"] != cursor["offset"]:
                _save_cursor(cursor_path, new_cursor)
            return 0

        model = models.most_common(1)[0][0] if models else "unknown"
        item_id, role = _attribution()
        with log.locked():
            log.append("usage.recorded", {
                "provider": PROVIDER,
                "source": SOURCE,
                "session_id": session_id,
                "model": model,
                "role": role,
                "units": {**totals, "messages": messages},
            }, item_id=item_id)
            _save_cursor(cursor_path, new_cursor)
    except Exception:       # a hook must never fail the interactive session
        return 0
    return 0


def register(sub) -> dict:
    p = sub.add_parser("hook", help="Claude Code hook entry points")
    hooks = p.add_subparsers(dest="hook_command", required=True)
    hooks.add_parser(
        "usage",
        help="record interactive-session usage from a Stop hook (JSON on stdin)",
    )
    return {"hook": _cmd}


def _cmd(args, log: EventLog) -> int:
    return handle_hook(sys.stdin, log)
