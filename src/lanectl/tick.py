"""One unattended step for a timer: doctor, reap expired deploys, then run lanes.

Ladder rung 4: a timer should be able to advance the estate without a planner
session in the loop.  ``tick`` runs the read-only health check first; an ERROR
finding stops the step before anything is reaped or dispatched.  Otherwise it
tears down due dev deploys and then runs the same admit/execute loop as
``lanectl run``, stopping at the first admit message that says nothing could be
claimed or after a worker infrastructure rejection.
"""
from __future__ import annotations

from . import deploy, doctor, runner

#: Substrings of an ``execute`` line that mean the worker itself failed.
INFRA_MARKERS = ("-> rejected: infra:", "-> rejected: infra")

BREAKER_LINE = "breaker: worker infrastructure failure; stopping this run loop"


def _run(log, max_items, lane) -> list[str]:
    """The ``lanectl run`` loop, returning the lines it would print."""
    lines: list[str] = []
    for _ in range(max_items):
        claim = runner.admit(lane, log)
        if isinstance(claim, str):
            lines.append(claim)
            return lines
        lines.append(f"claimed {claim.attempt_id} -> {claim.model}")
        out = runner.execute(claim, log)
        lines.append(out)
        if any(marker in out for marker in INFRA_MARKERS):
            lines.append(BREAKER_LINE)
            return lines
    return lines


def tick(log, *, max_items: int = 3, lane: str = "implement",
         doctor_fn=None, reap_fn=None, run_fn=None) -> dict:
    """Doctor first, then reap due deploys, then run up to *max_items* attempts."""
    findings = (doctor_fn or doctor.run)(log)
    levels = {finding.level for finding in findings}
    if doctor.ERROR in levels:
        return {"doctor": "error", "reaped": [], "ran": [], "stopped": "doctor"}
    status = "warn" if doctor.WARN in levels else "ok"
    reaped = (reap_fn or deploy.reap)(log)
    ran = (run_fn or _run)(log, max_items, lane)
    return {"doctor": status, "reaped": reaped, "ran": ran, "stopped": None}


def register(sub) -> dict:
    p = sub.add_parser("tick", help="one unattended step: doctor, reap expired "
                                   "deploys, then run lanes")
    p.add_argument("--max", type=int, default=3,
                   help="attempts to run after the health check (default 3)")
    p.add_argument("--lane", default="implement")
    return {"tick": _cmd}


def _cmd(args, log) -> int:
    out = tick(log, max_items=args.max, lane=args.lane)
    print(f"tick: doctor={out['doctor']} reaped={len(out['reaped'])} "
          f"ran={len(out['ran'])}")
    for line in (*out["reaped"], *out["ran"]):
        print(line)
    return 1 if out["doctor"] == "error" else 0
