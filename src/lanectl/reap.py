"""Close abandoned attempts so admission and concurrency caps recover.

A runner that dies leaves its attempt open forever: the item stays ``claimed``
and keeps a concurrency slot. The reaper is a deterministic projection fix-up:
an attempt claimed longer ago than the threshold with no ``attempt.finished``
is closed as failed and the item gets a follow-up (requeue or park).
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from .config import load_lane
from .events import EventLog

RULES_REVISION = "reaper/v1"


def _claimed_at(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def reap(log: EventLog, *, now: datetime, older_than_s: float,
         max_attempts: int) -> list[str]:
    """Close stale open attempts and return their ids (idempotent)."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    closed: list[str] = []
    with log.locked():
        events = log.read()
        claims = [e for e in events if e["type"] == "item.claimed" and e["item_id"]]
        finished = {e["data"]["attempt_id"] for e in events if e["type"] == "attempt.finished"}
        used = Counter((e["item_id"], e["data"].get("release_revision")) for e in claims)
        for e in claims:
            d, iid, aid = e["data"], e["item_id"], e["data"]["attempt_id"]
            if aid in finished:
                continue
            if (now - _claimed_at(e["ts"])).total_seconds() < older_than_s:
                continue
            log.append("attempt.finished", {
                "attempt_id": aid, "outcome": "failed", "exit_code": -1, "head_sha": "",
                "elapsed_s": 0.0, "escalation_reason": "abandoned"}, item_id=iid)
            log.append("decision.recorded", {
                "attempt_id": aid, "decision": "rejected", "reasons": ["abandoned"],
                "rules_revision": RULES_REVISION, "by": "reaper"}, item_id=iid)
            log.append("experiment.recorded", {
                "attempt_id": aid, "model": d.get("model", "unknown"),
                "worker": d.get("worker", "unknown"),
                "task_class": d.get("task_class", "unknown"), "decision": "rejected",
                "elapsed_s": 0.0, "rules_revision": RULES_REVISION, "by": "reaper"}, item_id=iid)
            if used[(iid, d.get("release_revision"))] >= max_attempts:
                log.append("item.parked", {"reason": "abandoned: attempts exhausted"}, item_id=iid)
            else:
                log.append("item.requeued", {"reason": "abandoned"}, item_id=iid)
            finished.add(aid)
            closed.append(aid)
    return closed


def register(sub) -> dict:
    p = sub.add_parser("reap", help="close abandoned attempts so caps recover")
    p.add_argument("--older-than", type=int, default=3600, metavar="SECONDS",
                   help="claimed longer ago than this (default 3600)")
    p.add_argument("--lane", default="implement")
    return {"reap": _cmd}


def _cmd(args, log: EventLog) -> int:
    lane = load_lane(args.lane)
    closed = reap(log, now=datetime.now(timezone.utc), older_than_s=args.older_than,
                  max_attempts=lane.max_attempts)
    for aid in closed:
        print(f"reaped {aid}")
    print(f"{len(closed)} abandoned attempt(s) closed")
    return 0
