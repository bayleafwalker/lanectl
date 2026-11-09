"""Close abandoned attempts so admission and concurrency caps recover.

A runner that dies leaves its attempt open forever: the item stays ``claimed``
and keeps a concurrency slot.  The same runner can also die *after*
``attempt.finished`` but before ``decision.recorded`` (2026-11-08: an old runner
hit a newer event type), leaving the item stuck in ``implemented``/``gated``.
The reaper is a deterministic projection fix-up for both cases: an attempt
older than the threshold with no decision gets one now.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import runner
from .config import load_lane, load_releases
from .events import EventLog, ItemView, project_items
from .gates import decision

RULES_REVISION = "reaper/v2"
RECOVERED_BY = "reaper/v2"


def _at(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def _stale(ts: str, now: datetime, older_than_s: float) -> bool:
    return (now - _at(ts)).total_seconds() >= older_than_s


def _recover(log: EventLog, events: list[dict], fin: dict, iid: str,
             release, max_attempts: int) -> bool:
    """Decide a finished-but-undecided attempt, then record what the runner would."""
    aid = fin["attempt_id"]
    claim = next((e["data"] for e in events
                  if e["type"] == "item.claimed" and e["data"]["attempt_id"] == aid), {})
    seed = fin.get("seed_sha") or claim.get("base_sha")
    if not seed:   # no diff baseline: ``changed`` is unknowable, leave it for a human
        return False
    gates: dict[str, list[str]] = {}
    for e in events:
        if e["type"] == "gate.result" and e["data"]["attempt_id"] == aid:
            gates[e["data"]["gate"]] = e["data"]["violations"]
    revision = claim.get("release_revision", release.revision if release else 0)
    if gates:
        used = runner.attempts_used(project_items(log.read())[iid], revision)
        changed = (fin.get("head_sha") or "") != seed
        dec, reasons, follow = decision.decide(gates, fin.get("outcome", "failed"), used,
                                               max_attempts, changed)
    else:   # died before gates ran: cannot accept, and must not burn an attempt
        dec, reasons, follow = ("rejected", ["infra: runner died before gates"],
                                "requeue-infra")
    runner.record_decision(
        log, item_id=iid, attempt_id=aid, model=claim.get("model", "unknown"),
        worker=claim.get("worker", "unknown"),
        task_class=release.task_class if release else "unknown",
        size=release.size if release else "unknown", dec=dec, reasons=reasons,
        follow=follow, elapsed_s=fin.get("elapsed_s", 0.0),
        lane_revision=claim.get("lane_revision"), gates=gates,
        extra={"recovered_by": RECOVERED_BY})
    runner.reconcile_capacity(log, events, aid, actual=None, outcome="recovered", item_id=iid)
    return True


def reap(log: EventLog, *, now: datetime, older_than_s: float,
         max_attempts: int) -> list[str]:
    """Close stale open attempts and decide stale finished ones; return their ids."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    closed: list[str] = []
    with log.locked():
        events = log.read()
        releases = {r.id: r for r in load_releases()}
        claims = [e for e in events if e["type"] == "item.claimed" and e["item_id"]]
        finished = {e["data"]["attempt_id"] for e in events if e["type"] == "attempt.finished"}
        decided = {e["data"]["attempt_id"] for e in events if e["type"] == "decision.recorded"}
        for e in events:   # finished, old, never decided: the runner died mid-step
            fin = e["data"]
            aid = fin.get("attempt_id")
            if e["type"] != "attempt.finished" or not aid or aid in decided:
                continue
            if not _stale(e["ts"], now, older_than_s):
                continue
            iid = e["item_id"] or next(
                (c["item_id"] for c in claims if c["data"]["attempt_id"] == aid), None)
            if iid is None:
                continue
            if _recover(log, events, fin, iid, releases.get(iid), max_attempts):
                decided.add(aid)
                closed.append(aid)
        views: dict[str, ItemView] = project_items(log.read())
        for e in claims:
            d, iid, aid = e["data"], e["item_id"], e["data"]["attempt_id"]
            if aid in finished:
                continue
            if not _stale(e["ts"], now, older_than_s):
                continue
            log.append("attempt.finished", {
                "attempt_id": aid, "outcome": "failed", "exit_code": -1, "head_sha": "",
                "elapsed_s": 0.0, "escalation_reason": "abandoned"}, item_id=iid)
            runner.reconcile_capacity(log, events, aid, actual=None, outcome="recovered",
                                      item_id=iid)
            log.append("decision.recorded", {
                "attempt_id": aid, "decision": "rejected", "reasons": ["abandoned"],
                "rules_revision": RULES_REVISION, "by": "reaper"}, item_id=iid)
            log.append("experiment.recorded", {
                "attempt_id": aid, "model": d.get("model", "unknown"),
                "worker": d.get("worker", "unknown"),
                "task_class": d.get("task_class", "unknown"), "decision": "rejected",
                "elapsed_s": 0.0, "rules_revision": RULES_REVISION, "by": "reaper"}, item_id=iid)
            # same counting as admission: this revision, infra failures excluded
            used = len([a for a in views[iid].attempts if a.get("release_revision") == d.get("release_revision")
                        and not a.get("infra")])
            if used >= max_attempts:
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
