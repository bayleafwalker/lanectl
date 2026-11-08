"""Close attempts whose runner died so admission and concurrency caps recover.

A claimed attempt with no ``attempt.finished`` holds a concurrency slot forever
when the worker process disappears. Reaping is a deterministic, append-only
repair: it closes the attempt as a failure, records the rejection and the
experiment, then returns the item to the queue -- or parks it when the lane's
attempt budget is already spent.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .config import load_lane
from .events import EventLog, ItemView, project_items

TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
REAPER = "reaper"


def _as_utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        return datetime.strptime(value, TS_FORMAT).replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _attempts_used(view: ItemView, attempt: dict) -> int:
    """Attempts charged to the attempt's revision up to and including it."""
    revision = attempt.get("release_revision", view.release_revision)
    used = 0
    for a in view.attempts:
        if a.get("release_revision", revision) == revision and not a.get("infra"):
            used += 1
        if a is attempt:
            break
    return used


def reap(log: EventLog, *, now: datetime | str, older_than_s: float,
         max_attempts: int) -> list[str]:
    """Close stale open attempts; return their attempt ids in log order."""
    moment = _as_utc(now)
    closed: list[str] = []
    with log.locked():
        events = log.read()
        finished = {e["data"]["attempt_id"] for e in events if e["type"] == "attempt.finished"}
        items = project_items(events)
        for view in items.values():
            for attempt in view.attempts:
                attempt_id = attempt["attempt_id"]
                if attempt_id in finished:
                    continue
                claimed = _as_utc(attempt["ts"])
                age_s = (moment - claimed).total_seconds()
                if age_s <= older_than_s:
                    continue
                used = _attempts_used(view, attempt)
                log.append("attempt.finished", {
                    "attempt_id": attempt_id, "outcome": "failed", "exit_code": -1,
                    "head_sha": "", "elapsed_s": round(age_s, 1)}, item_id=view.item_id)
                log.append("decision.recorded", {
                    "attempt_id": attempt_id, "decision": "rejected",
                    "reasons": ["abandoned: no attempt.finished; runner presumed dead"],
                    "rules_revision": REAPER, "by": REAPER}, item_id=view.item_id)
                log.append("experiment.recorded", {
                    "attempt_id": attempt_id, "model": attempt["model"],
                    "worker": attempt["worker"],
                    "task_class": attempt.get("task_class", "unknown"),
                    "decision": "rejected", "elapsed_s": round(age_s, 1),
                    "lane_revision": attempt.get("lane_revision"),
                    "rules_revision": REAPER}, item_id=view.item_id)
                if used >= max_attempts:
                    log.append("item.parked", {
                        "reason": f"abandoned; attempts exhausted ({used}/{max_attempts})"},
                        item_id=view.item_id)
                else:
                    log.append("item.requeued", {
                        "reason": "abandoned; runner died, attempt reaped"}, item_id=view.item_id)
                finished.add(attempt_id)
                closed.append(attempt_id)
    return closed


def register(subparsers) -> dict:
    p = subparsers.add_parser("reap", help="close abandoned attempts so caps recover")
    p.add_argument("--older-than", type=float, default=3600,
                   help="seconds before an unfinished claim counts as abandoned (default 3600)")
    p.add_argument("--lane", default="implement",
                   help="lane whose max_attempts decides requeue vs park (default implement)")
    return {"reap": _handle}


def _handle(args, log) -> int:
    lane = load_lane(args.lane)
    closed = reap(log, now=datetime.now(timezone.utc), older_than_s=args.older_than,
                  max_attempts=lane.max_attempts)
    print(f"reaped {len(closed)} abandoned attempt(s)"
          + (f": {', '.join(closed)}" if closed else ""))
    return 0
