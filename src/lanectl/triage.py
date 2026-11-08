"""Triage: turn failures into deduplicated work proposals.

A failed train is evidence of work to do. Instead of an operator noticing it
by hand, ``scan --record`` emits one ``triage.proposed`` event per failing
pytest node id, and :func:`proposals` folds the log into the open list,
deduplicated by fingerprint. Every recorded proposal stays open until a later
resolution event exists; there is none in contract v1 yet.
"""
from __future__ import annotations

import hashlib
import re

from .events import EventLog

# pytest short summary lines: "FAILED <nodeid>[ - msg]" / "ERROR <nodeid>[ - msg]".
# The node id is non-greedy so the first " - " starts the message.
_FAIL_LINE = re.compile(r"^(?:FAILED|ERROR) (.+?)(?: - .*)?$", re.MULTILINE)


def _fingerprint(repo: str, node_id: str) -> str:
    return hashlib.sha1(f"{repo}:{node_id}".encode()).hexdigest()


def failing_tests(output: str) -> list[str]:
    """Sorted unique pytest node ids named by FAILED/ERROR summary lines."""
    nodes = {m.group(1).strip() for m in _FAIL_LINE.finditer(output or "")}
    return sorted(node for node in nodes if node)


def from_train(event: dict) -> list[dict]:
    """``triage.proposed`` payloads for one failed ``train.built`` event.

    One proposal per failing node id parsed from ``check_tail``; when the tail
    names none (a setup or infrastructure failure), one proposal for the whole
    train keyed by its id.
    """
    if event.get("type") != "train.built":
        return []
    d = event.get("data") or {}
    if d.get("passed") is not False:
        return []
    repo = d.get("repo") or ""
    train_id = d.get("train_id") or ""
    nodes = failing_tests(d.get("check_tail") or "")
    whole_train = not nodes
    out = []
    for node in nodes or [train_id]:
        summary = (f"check failed in train {train_id}" if whole_train
                   else f"{node} failed in train {train_id}")
        out.append({"source": "train", "fingerprint": _fingerprint(repo, node),
                    "summary": summary, "repo": repo, "node_id": node,
                    "train_id": train_id})
    return out


def proposals(events: list[dict]) -> list[dict]:
    """Open proposals, deduplicated by fingerprint, in fingerprint order."""
    by_fp: dict[str, dict] = {}
    for ev in events:
        if ev.get("type") != "triage.proposed":
            continue
        d = ev.get("data") or {}
        fp = d.get("fingerprint")
        if not fp:
            continue
        p = by_fp.get(fp)
        if p is None:
            p = by_fp[fp] = {"fingerprint": fp, "source": d.get("source", ""),
                             "summary": d.get("summary", ""), "count": 0,
                             "first_ts": None, "last_ts": None, "train_ids": set()}
        p["count"] += 1
        ts = ev.get("ts")
        if ts:
            if p["first_ts"] is None or ts < p["first_ts"]:
                p["first_ts"] = ts
            if p["last_ts"] is None or ts > p["last_ts"]:
                p["last_ts"] = ts
        if d.get("train_id"):
            p["train_ids"].add(d["train_id"])
    out = []
    for fp in sorted(by_fp):
        p = by_fp[fp]
        p["train_ids"] = sorted(p["train_ids"])
        out.append(p)
    return out


def unscanned(events: list[dict]) -> list[dict]:
    """Proposals for failed trains with no recorded proposal yet.

    A train counts as scanned once a ``triage.proposed`` payload carries its
    ``train_id``; repeated ``train.built`` events for an already scanned train
    are ignored.
    """
    scanned = {e["data"].get("train_id") for e in events
               if e.get("type") == "triage.proposed"}
    out, seen = [], set()
    for ev in events:
        if ev.get("type") != "train.built":
            continue
        d = ev.get("data") or {}
        tid = d.get("train_id")
        if d.get("passed") is not False or not tid or tid in scanned or tid in seen:
            continue
        seen.add(tid)
        out.extend(from_train(ev))
    return out


def scan(log: EventLog, *, record: bool) -> list[dict]:
    """Return pending proposals; append them when *record* is set."""
    if not record:
        return unscanned(log.read())
    emitted: list[dict] = []
    with log.locked():
        for p in unscanned(log.read()):
            log.append("triage.proposed", p)
            emitted.append(p)
    return emitted


def register(sub) -> dict:
    p = sub.add_parser("triage", help="turn failures into deduplicated work proposals")
    sp = p.add_subparsers(dest="triage_cmd")
    s = sp.add_parser("scan", help="propose work for failed trains not yet scanned")
    s.add_argument("--record", action="store_true",
                   help="append triage.proposed events instead of only printing")
    return {"triage": _cmd}


def _cmd(args, log: EventLog) -> int:
    if getattr(args, "triage_cmd", None) == "scan":
        ps = scan(log, record=args.record)
        verb = "proposed" if args.record else "would propose"
        for p in ps:
            print(f"{verb} {p['summary']} ({p['fingerprint'][:12]})")
        print(f"{len(ps)} proposal(s) {'recorded' if args.record else 'pending'}")
        return 0
    open_ = proposals(log.read())
    if not open_:
        print("no open triage proposals")
        return 0
    for p in open_:
        print(f"{p['count']:>3}x {p['first_ts']}..{p['last_ts']} "
              f"{p['summary']} [{p['fingerprint'][:12]}]")
    return 0
