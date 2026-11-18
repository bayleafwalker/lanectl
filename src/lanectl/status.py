"""`lanectl status`: where am I, what needs me, what next (operator-interface contract, section 1).

Also owns the release classification shared with `lanectl ready`, so a release that
`ready` calls BLOCKED is never shown as actionable here.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone

from . import doctor, render, runner
from .config import home, load_lane, load_releases, load_repos
from .events import project_items
from .ready import readiness
from .render import clip, sym
from .vocab import SYMBOLS, classify

SCHEMA = "lanectl.status/v1"
#: Item states where a lane cannot take the item right now even though the release is ready.
IN_FLIGHT_STATES = frozenset({"claimed", "implemented", "gated", "candidate", "in-train", "parked"})
_RUNNING = ("claimed", "implemented", "gated")
_CAPS = {"needs": 5, "blocked": 3, "warnings": 3, "flight": 3}   # rows per section before "… N more"
MAX_LINES = 24   # the default view fits one terminal screen; sections shrink to fit, --all lifts it
_NEEDS = ("in-train", "candidate", "parked")   # item states waiting on a person, most urgent first


def release_rows(events: list[dict], lane_name: str = "implement", include_landed: bool = True) -> list[dict]:
    """One row per release: state READY/BLOCKED/LANDED or the in-flight item state, upper-cased."""
    lane, repos = load_lane(lane_name), load_repos()
    items = project_items(events)
    rows = []
    for rel in load_releases():
        v = items.get(rel.id)
        current = v is not None and v.release_revision >= rel.revision
        landed = current and v.state == "landed"
        if landed and not include_landed:
            continue
        if current and v.state in IN_FLIGHT_STATES:
            state, reasons = v.state.upper(), []
        else:
            reasons = [] if landed else readiness(rel, lane, repos)
            state = "LANDED" if landed else ("READY" if not reasons else "BLOCKED")
        rows.append({"id": rel.id, "state": state, "reasons": reasons, "repo": rel.repo,
                     "tries": len(v.attempts) if v else 0,
                     "reason": v.last_reason if v and state == "PARKED" else "",
                     "claimed_at": v.attempts[-1].get("ts") if v and v.attempts else None})
    return rows


def _unblock(rel_id: str) -> str:
    # Never `publish`: a draft may be a planner hold that only `show` explains.
    return f"lanectl backlog show {rel_id}"


def _context() -> dict:
    explicit = bool(os.environ.get("LANECTL_HOME"))
    return {"home": str(home()), "source": "env" if explicit else "cwd-or-install",
            "repos": sorted(load_repos())}


def build(log, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    events = log.read()
    rows = release_rows(events)
    needs = [{**r, "state": state} for state in _NEEDS for r in rows if r["state"].lower() == state]
    blocked = [{"id": r["id"], "reasons": r["reasons"], "fix": _unblock(r["id"])}
               for r in rows if r["state"] == "BLOCKED"]
    warnings = [{"level": f.level.lower(), "check": f.check, "detail": f.detail, "fix": f.fix}
                for f in doctor.collapse(doctor.run(log, now=now)) if f.level != doctor.OK]
    running = [{"id": r["id"], "state": r["state"].lower(), "age": render.ago(r["claimed_at"], now)}
               for r in rows if r["state"].lower() in _RUNNING]
    counts = Counter(r["state"].lower() for r in rows)
    doc = {"schema": SCHEMA, "context": {**_context(), "events": len(events)},
           "counts": dict(sorted(counts.items())), "needs_you": needs, "blocked": blocked,
           "landed": {"count": counts["landed"], "ids": [r["id"] for r in rows if r["state"] == "LANDED"]},
           "warnings": warnings, "in_flight": running,
           "lanes": [{"lane": l["lane"], "caps": l["caps"]} for l in _lanes(events)],
           "metrics": runner.metrics(events)}
    doc["next"] = _next(doc)
    return doc


def _lanes(events: list[dict]) -> list[dict]:
    from . import lanes
    return lanes.rows(events)


def _next(doc: dict) -> list[str]:
    out = []
    by_state: dict[str, dict] = {}
    for n in doc["needs_you"]:
        by_state.setdefault(n["state"], n)   # the first row of each state, in log order
    if "in-train" in by_state:
        out.append("lanectl candidates")
    if "candidate" in by_state:
        out.append(f"lanectl train {by_state['candidate']['repo']}")
    if "parked" in by_state:
        out.append(f"lanectl backlog show {by_state['parked']['id']}")
    if doc["blocked"] and len(out) < 3:
        out.append(doc["blocked"][0]["fix"])
    for w in doc["warnings"]:
        if w["fix"] and len(out) < 3:
            out.append(w["fix"])
    return out or ["lanectl ready"]


def _more(shown: int, total: int, hint: str = "--all") -> list[str]:
    return [f"  … {total - shown} more ({hint})"] if total > shown else []


def format_text(doc: dict, show_all: bool = False) -> str:
    caps = dict(_CAPS)
    while True:
        lines = _lines(doc, caps, show_all)
        biggest = max(caps, key=caps.get)
        if show_all or len(lines) <= MAX_LINES or caps[biggest] <= 1:
            return "\n".join(lines)
        caps[biggest] -= 1


def _lines(doc: dict, caps: dict, show_all: bool) -> list[str]:
    c = doc["context"]
    cap = lambda key, items: items if show_all else items[:caps[key]]
    out = [f"lanectl  home {c['home']} ({c['source']})",
           f"repos: {', '.join(c['repos'])} · {c['events']} events · "
           f"{doc['landed']['count']} landed", ""]
    needs, blocked = doc["needs_you"], doc["blocked"]
    if needs:
        out.append(f"{sym(SYMBOLS['needs'])} NEEDS YOU ({len(needs)})")
        shown = cap("needs", needs)
        width = max(len(n["id"]) for n in shown)
        for n in shown:
            why = clip(n["reason"], max(24, 76 - width)) if n["reason"] else f"{n['tries']} tries"
            out.append(f"  {render.state(n['state'])}{' ' * max(1, 11 - len(n['state']))}{n['id']:<{width}}  {why}")
        out += _more(len(cap("needs", needs)), len(needs))
    elif not blocked:
        out.append(f"{sym(SYMBOLS['ok'])} Nothing needs you.")
    if blocked:
        out += ["", f"{sym(SYMBOLS[classify('blocked')])} BLOCKED ({len(blocked)}; `lanectl ready` agrees)"]
        shown = cap("blocked", blocked)
        width = max(len(b["id"]) for b in shown)
        for b in shown:
            out.append(f"  {b['id']:<{width}}  {b['reasons'][0].split(' (')[0]} -> {b['fix']}")
        out += _more(len(cap("blocked", blocked)), len(blocked))
    if doc["warnings"]:
        out += ["", "WARNINGS"]
        for w in cap("warnings", doc["warnings"]):
            out.append(f"  {w['check']}: {w['detail']}" + (f" -> {w['fix']}" if w["fix"] else ""))
        out += _more(len(cap("warnings", doc["warnings"])), len(doc["warnings"]), hint="lanectl doctor")
    lanes = "  ".join(f"{l['lane']} {l['caps']['concurrency']['used']}/{l['caps']['concurrency']['limit']}"
                      for l in doc["lanes"] if "concurrency" in l["caps"])
    out += ["", f"{sym(SYMBOLS['running'])} IN FLIGHT: {len(doc['in_flight'])} running, "
                f"{doc['counts'].get('ready', 0)} ready" + (f" · lanes {lanes}" if lanes else "")]
    for r in cap("flight", doc["in_flight"]):
        out.append(f"  {r['state']:<12} {r['id']}  {r['age']}")
    out += _more(len(cap("flight", doc["in_flight"])), len(doc["in_flight"]))
    if show_all:
        out += ["", f"LANDED ({doc['landed']['count']})", *(f"  {i}" for i in doc["landed"]["ids"])]
    elif doc["landed"]["count"]:
        out.append(f"landed: {doc['landed']['count']} (lanectl status --all to list)")
    return [*out, "", *(f"next: {cmd}" for cmd in doc["next"])]


def register(sub) -> dict:
    p = sub.add_parser("status", help="what needs you, what is blocked, what to run next")
    p.add_argument("--all", action="store_true", help="show every row instead of the top few")
    p.add_argument("--json", action="store_true",
                   help='one object (schema "lanectl.status/v1") including precision metrics')
    return {"status": _cmd}


def _cmd(args, log) -> int:
    doc = build(log)
    print(json.dumps(doc, sort_keys=True) if args.json else format_text(doc, args.all))
    return 0
