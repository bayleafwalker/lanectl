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
import os
import socket
import hashlib
import subprocess
from pathlib import Path

from . import decisions, delivery_policy, runner
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
             release, max_attempts: int, *, allow_accept=True) -> bool:
    """Decide a finished-but-undecided attempt, then record what the runner would."""
    aid = fin["attempt_id"]
    claim = next((e["data"] for e in events
                  if e["type"] == "item.claimed" and e["data"]["attempt_id"] == aid), {})
    binding = delivery_policy.claim_binding(events, iid, claim)
    if binding is None:
        return False
    lane = delivery_policy.from_binding(binding)
    max_attempts = lane.max_attempts
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
                                               max_attempts, changed, policy_mode=lane.delivery_policy)
    else:   # died before gates ran: cannot accept, and must not burn an attempt
        dec, reasons, follow = ("rejected", ["infra: runner died before gates"],
                                "requeue-infra" if lane.delivery_policy == "legacy" else "park")
    if dec == "candidate":
        try:
            effective = delivery_policy.effective_lane(binding, load_lane(lane.lane))
        except (OSError, ValueError, KeyError, TypeError):
            return False
        # Existing gate records cannot establish newly tightened authority rules.
        authority = ("size_max", "routing", "caps", "protected_paths", "dependency_manifests",
                     "test_globs", "forbidden_added_patterns", "external_models", "timeout_s",
                     "allow_restricted", "effects", "sandbox")
        if any(getattr(effective, k) != getattr(lane, k) for k in authority):
            return False
    if not allow_accept and dec == "candidate":
        dec, reasons, follow = ("rejected", ["infra: abandoned runner; acceptance must be rerun"],
                                "requeue-infra" if lane.delivery_policy == "legacy" else "park")
    decisions.follow_applied(
        log, item_id=iid, attempt_id=aid, follow=follow,
        mechanism=decisions.MECHANISM_REAPER, reasons=reasons)
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


def select(events: list[dict], now: datetime, older_than_s: float, claim_filter=None):
    """The attempts reap() would act on: (finished-but-undecided, abandoned claims).

    Shared by `reap --dry-run` and reap() so the preview lists exactly what runs.
    """
    claims = [e for e in events if e["type"] == "item.claimed" and e["item_id"]]
    finished = {e["data"]["attempt_id"] for e in events if e["type"] == "attempt.finished"}
    decided = {e["data"]["attempt_id"] for e in events if e["type"] == "decision.recorded"}
    undecided = []
    for e in events:   # finished, old, never decided: the runner died mid-step
        aid = e["data"].get("attempt_id")
        if e["type"] != "attempt.finished" or not aid or aid in decided:
            continue
        claim = next((c for c in claims if c["data"]["attempt_id"] == aid), None)
        if claim_filter is not None and (claim is None or not claim_filter(claim)):
            continue
        if not _stale(e["ts"], now, older_than_s):
            continue
        iid = e["item_id"] or (claim["item_id"] if claim else None)
        if iid is not None:
            undecided.append((e, iid))
    abandoned = []
    for e in claims:
        aid = e["data"]["attempt_id"]
        if aid in finished or aid in decided:
            continue
        if claim_filter is not None and not claim_filter(e):
            continue
        if not _stale(e["ts"], now, older_than_s):
            continue
        binding = delivery_policy.claim_binding(events, e["item_id"], e["data"])
        if binding is not None:
            abandoned.append((e, binding))
    return undecided, abandoned


def reap(log: EventLog, *, now: datetime, older_than_s: float,
         max_attempts: int, claim_filter=None, allow_accept=True) -> list[str]:
    """Close stale open attempts and decide stale finished ones; return their ids."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    closed: list[str] = []
    with log.locked():
        events = log.read()
        releases = {r.id: r for r in load_releases()}
        undecided, abandoned = select(events, now, older_than_s, claim_filter)
        for e, iid in undecided:
            fin = e["data"]
            aid = fin["attempt_id"]
            if _recover(log, events, fin, iid, releases.get(iid), max_attempts, allow_accept=allow_accept):
                closed.append(aid)
        views: dict[str, ItemView] = project_items(log.read())
        for e, binding in abandoned:
            d, iid, aid = e["data"], e["item_id"], e["data"]["attempt_id"]
            lane = delivery_policy.from_binding(binding)
            # same counting as admission: this revision, infra failures excluded
            used = len([a for a in views[iid].attempts if a.get("release_revision") == d.get("release_revision")
                        and not a.get("infra")])
            if lane.delivery_policy == "review-progress":
                follow, reasons = "park", ["abandoned: progress review required"]
            elif used >= lane.max_attempts:
                follow, reasons = "park", ["abandoned: attempts exhausted"]
            else:
                follow, reasons = "requeue", ["abandoned"]
            decisions.follow_applied(
                log, item_id=iid, attempt_id=aid, follow=follow,
                mechanism=decisions.MECHANISM_REAPER, reasons=reasons)
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
            if follow == "park":
                log.append("item.parked", {"reason": reasons[0]}, item_id=iid)
            else:
                log.append("item.requeued", {"reason": reasons[0]}, item_id=iid)
            closed.append(aid)
    return closed


def register(sub) -> dict:
    p = sub.add_parser("reap", help="close abandoned attempts so caps recover (records events)")
    p.add_argument("--older-than", type=int, default=3600, metavar="SECONDS",
                   help="claimed longer ago than this (default 3600)")
    p.add_argument("--lane", default="implement", help="lane whose attempt limit applies (default implement)")
    p.add_argument("--dry-run", action="store_true", help="list claims that look abandoned; change nothing")
    p.add_argument("--yes", action="store_true", help="do not ask for confirmation on a terminal")
    return {"reap": _cmd}


def _cmd(args, log: EventLog) -> int:
    lane = load_lane(args.lane)
    if args.dry_run:
        now = datetime.now(timezone.utc)
        undecided, abandoned = select(log.read(), now, args.older_than)
        stale = [e["data"]["attempt_id"] for e, _ in undecided] + [e["data"]["attempt_id"] for e, _ in abandoned]
        print(f"would examine {len(stale)} open or undecided attempt(s) older than {args.older_than}s"
              + "".join(f"\n  {aid}" for aid in stale) + "\nnext: rerun without --dry-run")
        return 0
    from .render import confirm
    if not confirm("Close abandoned attempts (records events)?", yes=args.yes):
        print("cancelled; nothing changed")
        return 1
    closed = reap(log, now=datetime.now(timezone.utc), older_than_s=args.older_than,
                  max_attempts=lane.max_attempts)
    for aid in closed:
        print(f"reaped {aid}")
    print(f"✓ {len(closed)} abandoned attempt(s) closed\nnext: lanectl status")
    return 0


def process_identity(pid=None):
    """Kernel birth identity, without relying on PID existence alone."""
    pid = os.getpid() if pid is None else pid
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        start = stat[stat.rfind(')') + 2:].split()[19]
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        machine = hashlib.sha256(Path('/etc/machine-id').read_bytes().strip()).hexdigest()
        return {'host': socket.gethostname(), 'boot_id': boot, 'machine_id': machine,
                'pid': pid, 'start_ticks': start}
    except (OSError, IndexError, ValueError):
        return None


def runner_dead(identity):
    """True only when this host can prove the recorded process no longer exists."""
    if not isinstance(identity, dict):
        return False
    local = process_identity()
    if (local is None or identity.get('host') != local['host']
            or identity.get('machine_id') != local['machine_id']):
        return False
    pid = identity.get('pid')
    if (not isinstance(pid, int) or isinstance(pid, bool) or pid < 1 or not isinstance(identity.get('start_ticks'), str)
            or not identity['start_ticks'].isdigit()):
        return False
    if identity.get('boot_id') != local['boot_id']:
        return bool(identity.get('boot_id'))  # same machine, preceding boot
    current = process_identity(pid)
    if current is not None:
        return current['start_ticks'] != identity['start_ticks']
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except (PermissionError, OSError):
        return False
    return False  # procfs unreadable is unknown, not proof of death


def unit_inactive(unit):
    """An orphaned systemd sandbox can outlive its Python runner."""
    if not isinstance(unit, str) or not unit.startswith('lanectl-attempt-') or not unit.endswith('.service'):
        return False
    try:
        p = subprocess.run(['systemctl', '--user', 'show', unit,
                            '--property=ActiveState,LoadState'], capture_output=True,
                           text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    fields = dict(row.split('=', 1) for row in p.stdout.splitlines() if '=' in row)
    return (p.returncode in (0, 4) and fields.get('ActiveState') in ('inactive', 'failed')
            and fields.get('LoadState') in ('loaded', 'not-found'))


def periodic(log, *, lane_name='implement', now=None, unit_inactive_fn=None):
    """Recover proven abandoned local attempts before admitting more work.

    Age alone never steals a lease or a live process. Foreign, old-format or
    unreadable process facts remain manual/owner recovery. Recovered gate sets
    cannot become candidates automatically: the new attempt reruns all gates.
    """
    try:
        lane = load_lane(lane_name)
    except FileNotFoundError:
        return []
    def eligible(claim):
        d = claim['data']
        return (d.get('lane') == lane_name and runner_dead(d.get('runner_process'))
                and (unit_inactive_fn or unit_inactive)(d.get('worker_unit')))
    return reap(log, now=now or datetime.now(timezone.utc),
                older_than_s=max(3600, lane.timeout_s + 120), max_attempts=lane.max_attempts,
                claim_filter=eligible, allow_accept=False)
