"""lanectl: autonomous lane runner (stage-0 seed)."""
from __future__ import annotations

import argparse
import json
import sys

from . import runner
from .config import load_lane, load_releases, load_repos
from .events import EventLog, project_items
from .ready import readiness


# Command plugins: modules exposing register(subparsers) -> {cmd: handler(args, log) -> int}.
# Add one import per anchor line; keep the spacer lines so trains merge cleanly.
PLUGINS: list = []

# @anchor usage-hook

# spacer

# @anchor report

# spacer

# @anchor reap
from . import reap as reap_plugin

PLUGINS.append(reap_plugin)

# spacer

# @anchor capacity
from . import capacity as capacity_plugin

PLUGINS.append(capacity_plugin)

# spacer


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="lanectl", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="admit and execute attempts until caps or the queue stop it")
    r.add_argument("--lane", default="implement")
    r.add_argument("--item")
    r.add_argument("--max", type=int, default=1, help="attempts to run sequentially (default 1)")
    sub.add_parser("status", help="item states, pending candidates, precision")
    rd = sub.add_parser("ready", help="Definition-of-Ready report for every release")
    rd.add_argument("--lane", default="implement")
    sub.add_parser("candidates")
    t = sub.add_parser("train", help="build a candidate train on top of main and run the repo check")
    t.add_argument("repo")
    t.add_argument("--only", nargs="*")
    l = sub.add_parser("land", help="judgment plane: fast-forward main to a passed train")
    l.add_argument("train_id")
    rj = sub.add_parser("reject", help="integrator rejects a candidate (requeue, or --park)")
    rj.add_argument("attempt_id")
    rj.add_argument("reason")
    rj.add_argument("--park", action="store_true")
    ap = sub.add_parser("approve", help="judgment plane: accept a review-required parked attempt")
    ap.add_argument("attempt_id")
    ap.add_argument("note")
    ev = sub.add_parser("events", help="print the log tail")
    ev.add_argument("-n", type=int, default=30)
    ev.add_argument("--item")
    handlers = {}
    for plugin in PLUGINS:
        handlers.update(plugin.register(sub))
    a = p.parse_args(argv)
    log = EventLog()
    if a.cmd in handlers:
        return handlers[a.cmd](a, log)

    if a.cmd == "run":
        for _ in range(a.max):
            c = runner.admit(a.lane, log, only=a.item)
            if isinstance(c, str):
                print(c)
                return 0
            print(f"claimed {c.attempt_id} -> {c.model}", flush=True)
            out = runner.execute(c, log)
            print(out, flush=True)
            if "-> rejected: infra:" in out or "-> rejected: infra" in out:
                print("breaker: worker infrastructure failure; stopping this run loop", flush=True)
                return 3
        return 0
    if a.cmd == "status":
        events = log.read()
        items = project_items(events)
        for v in sorted(items.values(), key=lambda v: v.item_id):
            models = ",".join(m.split("/")[-1] for m in v.models_tried)
            print(f"{v.state:10} {v.item_id:40} r{v.release_revision} tries={len(v.attempts)} [{models}]"
                  + (f"  -- {v.last_reason[:120]}" if v.state in ("parked", "rejected", "requeued") else ""))
        print(json.dumps(runner.metrics(events), indent=1))
        return 0
    if a.cmd == "ready":
        lane, repos = load_lane(a.lane), load_repos()
        for rel in load_releases():
            rs = readiness(rel, lane, repos)
            print(f"{'READY' if not rs else 'BLOCKED':8} {rel.id}" + "".join(f"\n    - {x}" for x in rs))
        return 0
    if a.cmd == "candidates":
        for c in runner.candidates(log):
            print(f"{c['repo']:14} {c['attempt_id']:40} {c['branch']}  {c['title']}")
        return 0
    if a.cmd == "train":
        print(runner.build_train(log, a.repo, a.only))
        return 0
    if a.cmd == "land":
        print(runner.land(log, a.train_id))
        return 0
    if a.cmd == "approve":
        print(runner.approve(log, a.attempt_id, a.note))
        return 0
    if a.cmd == "reject":
        print(runner.integrator_reject(log, a.attempt_id, a.reason, a.park))
        return 0
    if a.cmd == "events":
        evs = [e for e in log.read() if not a.item or e["item_id"] == a.item]
        for e in evs[-a.n:]:
            print(json.dumps(e, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
