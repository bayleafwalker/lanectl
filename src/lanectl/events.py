"""Append-only event log (JSONL) and the item-state projection.

Seed storage is a local file guarded by an flock. The Postgres-backed control
plane replaces this behind the same append/read interface.
"""
from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from .contracts import make_event, validate_event


def state_dir() -> Path:
    d = Path(os.environ.get("LANECTL_STATE", Path.home() / ".local/state/lanectl"))
    d.mkdir(parents=True, exist_ok=True)
    return d


class EventLog:
    def __init__(self, path: Path | None = None):
        self.path = path or state_dir() / "events.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    @contextmanager
    def locked(self):
        with open(self.path.with_suffix(".lock"), "a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield self
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def append(self, etype: str, data: dict, *, item_id: str | None = None) -> dict:
        ev = make_event(etype, data, item_id=item_id)
        if etype == "release.publication.invalidated":
            from .publication import validate_invalidation
            validate_invalidation(ev, self.read())
        line = json.dumps(ev, sort_keys=True, separators=(",", ":"))
        with open(self.path, "a") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return ev

    def read(self, *, after: int = 0) -> list[dict]:
        """Read validated events strictly after a one-based local offset."""
        if type(after) is not int or after < 0:
            raise ValueError("event offset must be a nonnegative integer")
        out = []
        with open(self.path) as fh:
            for n, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    event = validate_event(json.loads(line))
                    if n > after:
                        out.append(event)
                except Exception as exc:  # a torn tail line must not hide the rest
                    raise ValueError(f"{self.path}:{n}: {exc}") from exc
        return out


@dataclass
class ItemView:
    item_id: str
    state: str = "ready"
    release_revision: int = 0
    attempts: list[dict] = field(default_factory=list)   # claimed payloads + outcome
    last_reason: str = ""

    @property
    def models_tried(self) -> list[str]:
        return [a["model"] for a in self.attempts]

    @property
    def open_attempt(self) -> dict | None:
        return self.attempts[-1] if self.state == "claimed" and self.attempts else None


def project_items(events: list[dict]) -> dict[str, ItemView]:
    """Fold the log into per-item state. Pure; order is log order."""
    items: dict[str, ItemView] = {}
    by_attempt: dict[str, dict] = {}
    for ev in events:
        iid, t, d = ev["item_id"], ev["type"], ev["data"]
        if t == "train.built" and d["passed"]:
            for aid in d["attempts"]:
                a = by_attempt.get(aid)
                if a and items[a["item_id"]].state == "candidate":
                    items[a["item_id"]].state = "in-train"
            continue
        if iid is None:
            continue
        v = items.setdefault(iid, ItemView(iid))
        if t == "release.published":
            if d["revision"] > v.release_revision:
                v.release_revision = d["revision"]
                if v.state in ("ready", "requeued", "parked", "rejected"):
                    v.state = "ready"   # a new revision makes a parked item ready again
        elif t == "item.claimed":
            a = dict(d, ts=ev["ts"], item_id=iid)
            v.attempts.append(a)
            by_attempt[d["attempt_id"]] = a
            v.state = "claimed"
        elif t == "attempt.finished":
            by_attempt.get(d["attempt_id"], {}).update(finished=d)
            v.state = "implemented"
        elif t == "gate.result":
            v.state = "gated"
        elif t == "decision.recorded":
            by_attempt.get(d["attempt_id"], {}).update(
                decision=d["decision"],
                infra=bool(d["reasons"]) and str(d["reasons"][0]).startswith("infra:"))
            v.state = d["decision"]
            v.last_reason = "; ".join(d["reasons"])
        elif t == "item.landed":
            v.state = "landed"
        elif t == "item.parked":
            v.state, v.last_reason = "parked", d["reason"]
        elif t == "item.requeued":
            v.state, v.last_reason = "requeued", d["reason"]
    return items


def open_log():
    """Select the configured authority consistently for CLI, hooks and timers.

    A host-persistent backend marker keeps invocations outside the checkout from
    silently writing a second local authority. Served errors never fall back.
    EventLog(path) remains the explicit local/snapshot implementation for tests.
    """
    marker = state_dir() / 'backend.json'
    repo = os.environ.get('LANECTL_STREAM_REPO')
    if marker.exists():
        raw = json.loads(marker.read_text())
        if raw.get('schema') != 'lanectl.backend/v1' or raw.get('backend') != 'served':
            raise ValueError('invalid lanectl backend marker; refusing a local fallback')
        if repo and repo != raw['repo']:
            raise ValueError('LANECTL_STREAM_REPO conflicts with selected served authority')
        repo, root, stream = raw['repo'], raw['home'], raw['stream']
    elif repo:
        from .config import home
        root, stream = home(), os.environ.get('LANECTL_STREAM_NAME', 'control')
    else:
        return EventLog()
    from .coordination import configured, CoordinationError
    from .remote_events import RemoteEventLog
    coordinator = configured(repo, root=root)
    if coordinator is None:
        raise CoordinationError('served lane stream selected but Vuoro owner configuration is missing')
    return RemoteEventLog(coordinator.client, state_dir() / 'stream-pending.json', stream=stream)
