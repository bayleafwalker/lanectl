"""Delivery loop: claim -> isolate -> implement -> gate -> decide -> record.

Also builds candidate trains and lands them. Scheduling and admission are
deterministic; no agent chooses what runs next.
"""
from __future__ import annotations

import functools
import hashlib
import os
import shutil
import subprocess
import time
import tomllib
import threading
import json
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import (adapters, capacity, decisions, deploy, evaluator, gatejobs, report,
               sandbox as sandboxing, work)
from .config import RepoSpec, load_lane, load_releases, load_repos, match
from .contracts import LaneRevision, WorkRelease
from .events import EventLog, ItemView, project_items, state_dir
from .gates import decision, diffpolicy, failonbase
from .ready import eligible_models, readiness

BOT = ["-c", "user.name=lanectl", "-c", "user.email=lanectl@localhost"]


def git(repo: Path, *args: str, check: bool = True) -> str:
    p = subprocess.run(["git", "-C", str(repo), *BOT, *args], capture_output=True, text=True)
    if check and p.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()}")
    return p.stdout.strip()


@dataclass
class Claim:
    rel: WorkRelease
    repo: RepoSpec
    lane: LaneRevision
    attempt_id: str
    model: str
    worker: str


# ---------------------------------------------------------------- admission

def attempts_used(view: ItemView, revision: int) -> int:
    """Attempts that count against max_attempts: this revision, not infra failures."""
    return len([a for a in view.attempts if a.get("release_revision") == revision and not a.get("infra")])


def candidate_weights(rel: WorkRelease, lane: LaneRevision, view: ItemView,
                      repo: RepoSpec | None = None, *, events=None) -> dict[str, float]:
    """Eligible weights the dispatch hash can choose from (retry filter applied)."""
    from . import specification
    weights = specification.implementation_models(rel, eligible_models(rel, lane, repo))
    if lane.retry == "different_model":
        untried = {m: w for m, w in weights.items() if m not in view.models_tried}
        weights = untried or weights
    weights = {m: w for m, w in weights.items() if w > 0}
    if events is not None:
        from . import learning, steering
        try:
            policy = learning.load_limits()
        except FileNotFoundError:
            policy = {}
        weights = steering.effective_weights(events, weights, rel.task_class, policy)
    return weights


def pick_model(rel: WorkRelease, lane: LaneRevision, view: ItemView,
               repo: RepoSpec | None = None, *, weights=None) -> str | None:
    weights = candidate_weights(rel, lane, view, repo) if weights is None else weights
    if not weights:
        return None
    # deterministic weighted choice: reproducible from the log
    h = int(hashlib.sha256(f"{rel.id}:{len(view.attempts)}".encode()).hexdigest(), 16)
    point = (h % 10_000) / 10_000 * sum(weights.values())
    acc = 0.0
    for m in sorted(weights):
        acc += weights[m]
        if point < acc:
            return m
    return sorted(weights)[-1]


def sync_releases(log: EventLog, releases: list[WorkRelease]) -> None:
    items = project_items(log.read())
    for rel in releases:
        v = items.get(rel.id)
        if v is None or v.release_revision < rel.revision:
            log.append("release.published", {"release_id": rel.id, "revision": rel.revision},
                       item_id=rel.id)


def provider_for(model: str) -> str:
    """Allocation-policy provider key for a routed model.

    ``opencode-go/*`` and ``opencode/*`` map to ``opencode``; ``claude-*`` maps
    to ``anthropic``, the allocation provider interactive Claude sessions draw
    on (``windows.provider_for``).  Any other model keeps the worker name, else
    the prefix before ``/``.
    """
    if model.startswith("claude-"):
        return "anthropic"
    try:
        return adapters.worker_for(model)
    except ValueError:
        return model.split("/", 1)[0]


def record_shadow(log: EventLog, events: list[dict], rel: WorkRelease, model: str | None,
                  static: str) -> None:
    """Append what capacity *would* have decided; it never changes the static answer."""
    provider = provider_for(model) if model else None
    try:
        policy = capacity.AllocationPolicy.load()
    except capacity.PolicyError:
        policy = None      # a broken shadow policy must never stop static admission
    verdict = capacity.capacity_admission(events, policy, datetime.now(timezone.utc),
                                          provider, rel.size)
    log.append("admission.shadow", {
        "static": static, "capacity": verdict["decision"],
        "agree": static == verdict["decision"], "reasons": verdict["reasons"],
        "release_id": rel.id, "size": rel.size, "provider": provider,
        "estimate": verdict["estimate"], "burnable": verdict["burnable"],
    }, item_id=rel.id)


def reserve_capacity(log: EventLog, events: list[dict], rel: WorkRelease,
                     provider: str | None, attempt_id: str) -> bool:
    """Reserve the attempt's estimated burn before it starts, atomically.

    Only a provider the allocation policy names is reserved: an unknown provider
    would not be gated at admission, so holding capacity for it would invent a
    ledger entry.  Called inside the admission lock, right after ``item.claimed``.
    """
    if provider is None:
        return False
    try:
        policy = capacity.AllocationPolicy.load()
    except capacity.PolicyError:
        policy = None      # a broken policy must never stop admission
    if policy is None or provider not in policy.providers:
        return False
    spec = policy.providers[provider]
    amount = capacity.estimate(events, policy, provider, rel.size)
    if amount is None:
        return False
    log.append("capacity.reserved", {
        "reservation_id": f"res-{attempt_id}", "provider": provider,
        "pool": spec.pool, "unit": spec.unit, "amount": amount,
        "attempt_id": attempt_id}, item_id=rel.id)
    return True


def usage_actual(unit: str | None, usage: dict | None) -> int | float | None:
    """Adapter-reported ``unit`` usage, or None when it reported none."""
    if not isinstance(usage, dict):
        return None
    value = usage.get(unit)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def open_reservation(events: list[dict], attempt_id: str) -> dict | None:
    """The attempt's ``capacity.reserved`` payload that no reconciliation closed."""
    reconciled = {str((e.get("data") or {}).get("reservation_id"))
                  for e in events
                  if isinstance(e, dict) and e.get("type") == "capacity.reconciled"}
    for ev in events:
        data = ev.get("data") if isinstance(ev, dict) else None
        if not isinstance(data, dict) or ev.get("type") != "capacity.reserved":
            continue
        if data.get("attempt_id") != attempt_id:
            continue
        if str(data.get("reservation_id")) in reconciled:
            continue
        return data
    return None


def reconcile_capacity(log: EventLog, events: list[dict], attempt_id: str, *,
                       actual: int | float | None, outcome: str,
                       item_id: str | None = None) -> bool:
    """Reconcile an attempt's open reservation, at most once."""
    reservation = open_reservation(events, attempt_id)
    if reservation is None:
        return False
    log.append("capacity.reconciled", {
        "reservation_id": reservation["reservation_id"], "actual": actual,
        "outcome": outcome}, item_id=item_id)
    return True


def _coordinated(repo_name):
    from .config import home
    path = home() / "governance" / "vuoro.toml"
    return path.exists() and repo_name in tomllib.loads(path.read_text()).get("repos", {})


def _retry_admission(fn):
    @functools.wraps(fn)
    def bounded_retry(*args, **kwargs):
        from .remote_events import StreamConflict
        for _ in range(3):
            try:
                return fn(*args, **kwargs)
            except StreamConflict:
                continue  # no external execution occurred before claim commit
        return "served admission changed concurrently; retry next tick"
    return bounded_retry


@_retry_admission
def admit(lane_name: str, log: EventLog, only: str | None = None) -> Claim | str:
    """Return a Claim, or a string saying why nothing was admitted.

    Static caps decide admission.  Whenever at least one release is ready the
    capacity projection is also recorded as ``admission.shadow``, so the two
    policies can be compared before capacity is allowed to gate anything.
    """
    lane, repos, releases = load_lane(lane_name), load_repos(), load_releases()
    cycle_id = decisions.new_cycle_id()
    with log.locked():
        sync_releases(log, releases)
        events = log.read()
        items = project_items(events)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        running = sum(1 for v in items.values() if v.state == "claimed")
        infra = {a["attempt_id"] for v in items.values() for a in v.attempts if a.get("infra")}
        claimed_today = sum(1 for e in events if e["type"] == "item.claimed"   # infra failures cost nothing
                            and e["ts"].startswith(today) and e["data"]["lane"] == lane.lane
                            and e["data"]["attempt_id"] not in infra)
        unlanded = sum(1 for v in items.values() if v.state in ("candidate", "in-train"))
        ready: list[tuple[WorkRelease, ItemView]] = []
        for rel in releases:
            if only and rel.id != only:
                continue
            v = items.get(rel.id)
            if v is None or v.state not in ("ready", "requeued"):
                continue
            if attempts_used(v, rel.revision) >= lane.max_attempts:
                continue
            ready.append((rel, v))

        def blocked(reason: str) -> str:
            """A static cap refused: shadow the same release capacity would have seen."""
            if ready:
                rel, v = ready[0]
                record_shadow(log, events, rel, pick_model(rel, lane, v), "block")
            decisions.refused(log, lane=lane, cycle_id=cycle_id, reasons=[reason],
                              item_id=ready[0][0].id if ready else None)
            return reason

        if running >= lane.caps["concurrency"]:
            return blocked(f"cap: concurrency {running}/{lane.caps['concurrency']}")
        if claimed_today >= lane.caps["items_per_day"]:
            return blocked(f"cap: items_per_day {claimed_today}/{lane.caps['items_per_day']}")
        if unlanded >= lane.caps["accepted_unlanded_max"]:
            return blocked(f"cap: accepted_unlanded {unlanded}/{lane.caps['accepted_unlanded_max']} "
                           "(integrate first)")
        skipped = []
        for rel, v in ready:
            reasons = readiness(rel, lane, repos)
            if _coordinated(rel.repo) and lane.sandbox.get("mode") != "systemd-run":
                reasons.append("coordinated execution requires credential-isolating systemd sandbox")
            if _coordinated(rel.repo) and getattr(repos.get(rel.repo), 'train_isolation', 'namespace') != 'namespace':
                reasons.append("coordinated execution requires namespace train isolation")
            if _coordinated(rel.repo) and (not rel.work or not rel.work_complete
                                              or rel.work.split("#", 1)[0] != rel.repo):
                reasons.append("coordinated releases require a complete Work outcome")
            if reasons:
                skipped.append(f"{rel.id}: {'; '.join(reasons)}")
                continue
            alternatives = candidate_weights(rel, lane, v, repos.get(rel.repo), events=events)
            model = pick_model(rel, lane, v, repos.get(rel.repo), weights=alternatives)
            if model is None:
                skipped.append(f"{rel.id}: no eligible model")
                continue
            from . import steering
            try:
                policy = capacity.AllocationPolicy.load()
            except capacity.PolicyError:
                policy = None
            provider = provider_for(model)
            spec = policy.providers.get(provider) if policy is not None else None
            verdict = steering.admission(events, policy, datetime.now(timezone.utc),
                                         provider, rel.size, model,
                                         enforce=spec is not None and spec.admission_mode == "enforce")
            if verdict["decision"] == "block":
                skipped.append(f"{rel.id}: {'; '.join(verdict['reasons'])}")
                continue
            n = len(v.attempts) + 1
            attempt_id = f"{rel.id}-a{n}"
            worker = adapters.worker_for(model)
            from . import reap
            identity = reap.process_identity()
            worker_unit = sandboxing.from_lane(lane.sandbox, (), lane.timeout_s + 120, attempt_id=attempt_id).unit
            log.append("item.claimed", {
                "attempt_id": attempt_id, "lane": lane.lane, "lane_revision": lane.revision,
                "lane_digest": lane.digest, "model": model, "worker": worker,
                "release_revision": rel.revision, "base_sha": rel.base_sha,
                "branch": f"lane/{attempt_id}", "runner_process": identity,
                "worker_unit": worker_unit if lane.sandbox.get("mode") == "systemd-run" else None}, item_id=rel.id)
            reserve_capacity(log, events, rel, provider_for(model), attempt_id)
            decisions.dispatch(log, lane=lane, rel=rel, attempt_id=attempt_id,
                               cycle_id=cycle_id, model=model, alternatives=alternatives)
            record_shadow(log, events, rel, model, "admit")
            return Claim(rel, repos[rel.repo], lane, attempt_id, model, worker)
        if ready:
            rel, v = ready[0]
            record_shadow(log, events, rel, pick_model(rel, lane, v), "block")
        decisions.refused(log, lane=lane, cycle_id=cycle_id,
                          reasons=["nothing ready", *skipped],
                          item_id=ready[0][0].id if ready else None)
        return "nothing ready" + ("".join(f"\n  not ready: {s}" for s in skipped))


# ---------------------------------------------------------------- execution

def render_prompt(rel: WorkRelease, lane: LaneRevision, repo: RepoSpec | None = None) -> str:
    bullets = lambda xs: "\n".join(f"- {x}" for x in xs) or "- (none)"
    protected = (*lane.protected_paths, *(repo.protected_paths if repo else ()))
    return f"""You own one bounded outcome in this git checkout (your working directory; stay inside it). Work autonomously:
discover, plan, implement and verify. Do not ask questions.

# Outcome: {rel.title}
{rel.outcome}

# Acceptance (run by an independent gate after you finish)
{bullets(rel.acceptance.exec)}
Planner-owned acceptance files (read them, never edit them):
{bullets(rel.acceptance.files)}

# Write scope (changes outside these globs are rejected)
{bullets(rel.scope_paths)}

# Constraints
{bullets(rel.constraints)}
- Do not modify or delete existing tests; add new test files instead.
- Any test you add must fail without your change.
- No skip/xfail markers, no new dependencies{"" if not rel.allow_deps else " unless required"}.
- Keep the change under ~{lane.size_budget_lines.get(rel.size, 0)} changed lines.
- Do not touch: {", ".join(protected)} (except paths your write scope names explicitly;
  those changes are reviewed interactively before landing).
- Commits are optional; uncommitted changes are collected.

# Escalate instead of guessing when
{bullets(rel.escalate_when + ("the outcome needs a change outside the write scope",
                               "the acceptance criteria look wrong or contradictory"))}
To escalate, stop and end your final message with:
DISPATCH_OUTCOME: ESCALATED
ESCALATION_REASON: <one line>
"""


def _copy_acceptance(rel: WorkRelease, wt: Path) -> dict[str, bytes]:
    out = {}
    for f in rel.acceptance.files:
        data = (Path(rel.release_dir) / "files" / f).read_bytes()
        dst = wt / f
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        out[f] = data
    return out


def _commit_all(wt: Path, msg: str) -> str:
    git(wt, "add", "-A")
    if git(wt, "status", "--porcelain"):
        git(wt, "commit", "-q", "--no-verify", "-m", msg)
    return git(wt, "rev-parse", "HEAD")


def _discard(repo: RepoSpec, path: Path) -> None:
    git(repo.path, "worktree", "remove", "--force", str(path), check=False)
    shutil.rmtree(path, ignore_errors=True)
    git(repo.path, "worktree", "prune", check=False)


def _main_fingerprint(repo: RepoSpec) -> str:
    """Main checkout state: HEAD, the main ref, tracked and untracked files.
    (2026-11-08: a leaked session committed straight onto main; status alone missed it.)"""
    return "\n".join((git(repo.path, "rev-parse", "HEAD", check=False),
                       git(repo.path, "rev-parse", f"refs/heads/{repo.main}", check=False),
                       git(repo.path, "status", "--porcelain", "--untracked-files=all", check=False)))


_owner_context = threading.local()


def _coordination_park(c, log, error):
    events = log.read()
    if not any(e["type"] == "attempt.finished" and e["data"]["attempt_id"] == c.attempt_id for e in events):
        log.append("attempt.finished", {"attempt_id": c.attempt_id, "outcome": "failed",
                   "exit_code": -1, "head_sha": "", "elapsed_s": 0.0,
                   "escalation_reason": "owner coordination unavailable"}, item_id=c.rel.id)
    with log.locked():
        reconcile_capacity(log, log.read(), c.attempt_id, actual=None, outcome="recovered", item_id=c.rel.id)
    record_decision(log, item_id=c.rel.id, attempt_id=c.attempt_id, model=c.model,
                    worker=c.worker, task_class=c.rel.task_class, size=c.rel.size,
                    dec="parked", reasons=["owner coordination unavailable: " + str(error)[:300]],
                    follow="park", elapsed_s=0.0, lane_revision=c.lane.revision, gates={})
    return f"{c.attempt_id}: parked: owner coordination unavailable"


def _coordinate_execution(native):
    @functools.wraps(native)
    def execute(c: Claim, log: EventLog, adapter_fn=None, *, require_coordination=False,
                expected_owner=None) -> str:
        from . import coordination, integrator
        try:
            owner = coordination.configured(c.repo.name)
            if owner is None:
                if require_coordination:
                    raise coordination.CoordinationError("owner coordination is not configured")
                return native(c, log, adapter_fn)
            if expected_owner is not None:
                # A preview binds the owner audience it was shown against.  If
                # the configured endpoint/repository moved, refuse rather than
                # execute against a different owner.
                client = getattr(owner, "client", None)
                for key in ("endpoint", "repo_id"):
                    if key in expected_owner and expected_owner[key] is not None \
                            and getattr(client, key, None) != expected_owner[key]:
                        raise coordination.CoordinationError(
                            f"owner {key} changed since the preview")
            if c.lane.sandbox.get("mode") != "systemd-run":
                raise coordination.CoordinationError("coordinated execution requires credential-isolating systemd sandbox")
            if c.repo.train_isolation != 'namespace':
                raise coordination.CoordinationError("coordinated execution requires namespace train isolation")
            if (not c.rel.work or not c.rel.work_complete
                    or c.rel.work.split("#", 1)[0] != c.rel.repo):
                raise coordination.CoordinationError("coordinated releases require a complete Work outcome")
            work_id = int(c.rel.work.split("#", 1)[1])
            owner.start(c.attempt_id, work_id, c.model,
                        "sha256:" + hashlib.sha256(render_prompt(c.rel, c.lane, c.repo).encode()).hexdigest(),
                        recipe_id=f"lanectl/{c.lane.lane}/v{c.lane.revision}")
            cancel = threading.Event()
            sandbox_holder = []
            def lost():
                cancel.set()
                if sandbox_holder:
                    sandbox_holder[0].cancel()
            settlement = None
            with owner.guard(c.attempt_id, on_lost=lost) as guard:
                _owner_context.guard = guard
                out = native(c, log, adapter_fn, lease_guard=guard,
                               cancel_event=cancel, sandbox_holder=sandbox_holder)
                guard.assert_active()
                view = project_items(log.read())[c.rel.id]
                owner.append_evidence(c.attempt_id, "candidate", "Observation",
                                      {"release_id": c.rel.id, "attempt_id": c.attempt_id,
                                       "state": view.state, "result": out})
                if view.state == "candidate":
                    integrator.cycle(log, only_attempt=c.attempt_id)
                guard.assert_active()
                landings = [e for e in log.read() if e["type"] == "item.landed"
                            and e["data"]["attempt_id"] == c.attempt_id]
                if landings and c.rel.work_complete:
                    receipt = landings[-1]["data"]
                    if c.repo.landing == "pr" and not work.merged(c.repo, receipt["landed_sha"]):
                        return out + "; owner completion awaits canonical merge"
                    owner.append_evidence(c.attempt_id, "landed", "Observation", receipt)
                    settlement = receipt
            # Stop background heartbeats before settlement deactivates the lease.
            # report_outcome itself revalidates authority, or replays exact uncertain bytes.
            if settlement is None and view.state not in ("candidate", "in-train", "landed"):
                owner.report_outcome(c.attempt_id, "failed", "Lane attempt did not pass acceptance",
                                     payload={"release_id": c.rel.id, "state": view.state})
            if settlement is not None:
                completed = work.report_owner_completion(owner, c.attempt_id, c.rel, settlement)
                log.append("work.synced", {"work": c.rel.work, "train_id": settlement["train_id"],
                           "closed": completed, "ok": True, "owner_reported": True,
                           "pending_owner": not completed}, item_id=c.rel.id)
            return out
        except Exception as exc:
            # After an acknowledged landing, uncertainty belongs in the owner journal;
            # never rewrite a successful Git effect as a failed implementation.
            if any(e["type"] == "item.landed" and e["data"]["attempt_id"] == c.attempt_id for e in log.read()):
                return f"{c.attempt_id}: landed; owner completion pending: {type(exc).__name__}"
            return _coordination_park(c, log, exc)
        finally:
            _owner_context.guard = None

    return execute


@_coordinate_execution
def execute(c: Claim, log: EventLog, adapter_fn=None, *, lease_guard=None,
             cancel_event=None, sandbox_holder=None) -> str:
    rel, repo, lane = c.rel, c.repo, c.lane
    wt = repo.worktree_root / c.attempt_id
    branch = f"lane/{c.attempt_id}"
    repo.worktree_root.mkdir(parents=True, exist_ok=True)
    _discard(repo, wt)
    git(repo.path, "branch", "-D", branch, check=False)
    # A standalone clone, not a linked worktree: harnesses such as OpenCode resolve a
    # linked worktree to the main repository root and write there (2026-11-08 breach).
    git(repo.path, "clone", "-q", "--shared", "--no-checkout", str(repo.path), str(wt))
    git(wt, "checkout", "-q", "-b", branch, rel.base_sha)
    git(wt, "remote", "remove", "origin", check=False)   # do not advertise the main checkout
    from .config import home
    # Control state and checkout authority must stay outside worker writes even
    # when they live outside the lane's declared filesystem roots.
    protected_roots = [*lane.sandbox.get("readonly", ()), str(state_dir().resolve()),
                       str(home().resolve()), str(Path(repo.path).resolve())]
    sandbox_policy = dict(lane.sandbox, readonly=list(dict.fromkeys(protected_roots)))
    sb = sandboxing.from_lane(sandbox_policy, (str(wt.resolve()),), lane.timeout_s + 120,
                              **({"attempt_id": c.attempt_id} if lease_guard is not None or adapter_fn is None else {}))
    if sandbox_holder is not None:
        sandbox_holder.append(sb)
    acc = _copy_acceptance(rel, wt)
    seed_sha = _commit_all(wt, f"lane(acceptance): {rel.id} r{rel.revision}")
    native_env = dict(os.environ)
    native_env.pop("CREDENTIALS_DIRECTORY", None)
    vuoro_config = home() / "governance" / "vuoro.toml"
    if vuoro_config.exists():
        config = tomllib.loads(vuoro_config.read_text())
        for target in config.get("repos", {}).values():
            native_env.pop(target.get("token_env", ""), None)
    if repo.setup_cmd:
        _train_command(repo, wt, repo.setup_cmd)

    runs = state_dir() / "runs"
    runs.mkdir(exist_ok=True)
    shims = sb.shim_dir(state_dir() / "shims" / c.attempt_id, ("opencode", "codex", "claude"))
    env = dict(native_env or os.environ, PATH=f"{shims}{os.pathsep}{os.environ.get('PATH', '')}") if shims else native_env
    if lease_guard is not None:
        lease_guard.assert_active()
    main_before = _main_fingerprint(repo)
    started = time.monotonic()
    fn = adapter_fn or adapters.ADAPTERS[c.worker]
    try:
        res = fn(model=c.model, worktree=wt, prompt=render_prompt(rel, lane, repo),
                 status_file=runs / f"{c.attempt_id}.json", timeout_s=lane.timeout_s,
                 external=c.model in lane.external_models, env=env,
                 **({"cancel_event": cancel_event} if cancel_event is not None and adapter_fn is None else {}),
                 **({"stop_callback": sb.cancel} if adapter_fn is None and c.worker in ("opencode", "codex", "claude") else {}),
                 **({"sandbox": sb} if c.worker == "local" else {}))
    except Exception as exc:  # adapter crash is an attempt outcome, not a runner crash
        res = adapters.AdapterResult("failed", 1, f"adapter error: {exc}", None)
    elapsed = round(time.monotonic() - started, 1)
    main_changed = _main_fingerprint(repo) != main_before
    # With a write sandbox the worker cannot touch main, so a change there is the
    # planner/integrator working concurrently: record it, do not fail the attempt.
    breach = main_changed and sb.mode == "none"
    # a worker may leave build junk; collect only what git would track
    head = _commit_all(wt, f"lane(attempt): {c.attempt_id} [{c.model}]")
    log.append("attempt.finished", {"attempt_id": c.attempt_id, "outcome": res.outcome,
               "exit_code": res.exit_code, "head_sha": head, "seed_sha": seed_sha,
               "elapsed_s": elapsed, "escalation_reason": res.escalation_reason,
               "final_tail": res.final_tail[-1500:], "isolation_breach": breach,
               "main_changed": main_changed}, item_id=rel.id)
    git(repo.path, "fetch", "-q", str(wt), f"+{branch}:{branch}")
    if res.usage:
        log.append("usage.recorded", {"provider": provider_for(c.model), "source": "adapter",
                   "units": res.usage, "attempt_id": c.attempt_id, "model": c.model}, item_id=rel.id)
    # Hold the log lock across read-and-append: a concurrent reap must not also
    # see this reservation open and reconcile it a second time.
    with log.locked():
        events = log.read()
        reservation = open_reservation(events, c.attempt_id)
        if reservation is not None:
            reconcile_capacity(log, events, c.attempt_id,
                               actual=usage_actual(reservation.get("unit"), res.usage),
                               outcome="completed", item_id=rel.id)

    if lease_guard is not None:
        lease_guard.assert_active()
    if breach:
        res = adapters.AdapterResult("failed", res.exit_code, res.final_tail, None)
        gates = {}
        head = seed_sha   # never gate or land work produced during a breach
    elif res.outcome == "failed" and head == seed_sha:
        gates = {}   # nothing to gate; decide() classifies this as infra
    else:
        gates = run_gates(c, wt, seed_sha, head, acc, res.outcome, sb)
    for g, vs in gates.items():
        log.append("gate.result", {"attempt_id": c.attempt_id, "gate": g, "passed": not vs,
                                   "violations": vs}, item_id=rel.id)
    view = project_items(log.read())[rel.id]
    used = attempts_used(view, rel.revision)
    dec, reasons, follow = decision.decide(gates, res.outcome, used, lane.max_attempts,
                                           changed=head != seed_sha)
    if breach:
        reasons = ["infra: isolation breach - main checkout changed during the attempt; inspect it"]
    if lease_guard is not None:
        lease_guard.assert_active()
    record_decision(log, item_id=rel.id, attempt_id=c.attempt_id, model=c.model,
                    worker=c.worker, task_class=rel.task_class, size=rel.size, dec=dec,
                    reasons=reasons, follow=follow, elapsed_s=elapsed,
                    lane_revision=lane.revision, gates=gates)
    decisions.transition(log, lane=lane, rel=rel, attempt_id=c.attempt_id,
                         follow=follow, reasons=reasons)
    if dec != "candidate":
        _discard(repo, wt)
    return f"{c.attempt_id} [{c.model}] -> {dec}: {'; '.join(reasons)[:400]}"


def record_decision(log: EventLog, *, item_id: str, attempt_id: str, model: str,
                    worker: str, task_class: str, size: str, dec: str, reasons: list[str],
                    follow: str, elapsed_s: float = 0.0, lane_revision: int | None = None,
                    gates: dict[str, list[str]] | None = None,
                    extra: dict | None = None) -> None:
    """Record a decision and everything the runner records after it.

    Shared with the reaper so a recovered attempt leaves the same trail the
    runner would have left.  ``extra`` adds fields to ``decision.recorded``.
    """
    payload = {"attempt_id": attempt_id, "decision": dec, "reasons": reasons,
               "rules_revision": decision.RULES_REVISION, "by": "gates"}
    payload.update(extra or {})
    log.append("decision.recorded", payload, item_id=item_id)
    if dec == "candidate":          # the evaluator predicts only gate-accepted attempts
        data = evaluator.evaluate_attempt(log, attempt_id)
        if data is None:            # no policy or no measurable diff to predict from
            rules = _evaluator_rules()
            decisions.acceptance_proposed(
                log, item_id=item_id, attempt_id=attempt_id,
                chosen=rules["default"], policy_revision=f"evaluator/v{rules['revision']}",
                reasons=["preliminary: no evaluation recorded"])
    log.append("experiment.recorded", {"attempt_id": attempt_id, "model": model, "worker": worker,
               "task_class": task_class, "size": size, "decision": dec, "elapsed_s": elapsed_s,
               "lane_revision": lane_revision, "rules_revision": decision.RULES_REVISION,
               "gates_failed": sorted(g for g, vs in (gates or {}).items() if vs)}, item_id=item_id)
    if follow in ("requeue", "requeue-infra"):
        log.append("item.requeued", {"reason": reasons[0] if reasons else dec}, item_id=item_id)
    elif follow == "park":
        log.append("item.parked", {"reason": "; ".join(reasons)[:500]}, item_id=item_id)


def run_gates(c: Claim, wt: Path, seed_sha: str, head: str, acc: dict[str, bytes],
              worker_outcome: str, sb=None) -> dict[str, list[str]]:
    wrap = sb.wrap_shell if sb else None
    rel, repo, lane = c.rel, c.repo, c.lane
    changes = diffpolicy.collect(wt, seed_sha, head)
    gates = {"diff-policy": diffpolicy.evaluate(changes, rel, lane, rel.acceptance.files,
                                                repo.protected_paths)}
    if diffpolicy.is_protected_violation(gates["diff-policy"]) or worker_outcome == "escalated":
        return gates
    new_tests = {ch.path: (wt / ch.path).read_bytes() for ch in changes
                 if ch.status == "A" and match(ch.path, lane.test_globs) and (wt / ch.path).is_file()}
    gates["fail-on-base"] = failonbase.check(repo.path, rel.base_sha, new_tests, repo.test_cmd,
                                             repo.setup_cmd, wrap=wrap)
    acc_tests = {f: d for f, d in acc.items() if match(f, lane.test_globs)}
    if rel.acceptance.fail_on_base and acc_tests:
        gates["acceptance-on-base"] = [f"spec-gap {v}" for v in failonbase.check(
            repo.path, rel.base_sha, acc_tests, repo.test_cmd, repo.setup_cmd, wrap=wrap)]
    for f, data in acc.items():   # belt and braces: gate the planner's bytes, not the worker's
        (wt / f).write_bytes(data)
    fails = []
    for cmd in rel.acceptance.exec:
        p = subprocess.run(wrap(cmd, wt) if wrap else cmd, shell=True, cwd=wt,
                           capture_output=True, text=True, timeout=1800)
        if p.returncode:
            fails.append(f"exit {p.returncode}: {cmd} :: {(p.stdout + p.stderr)[-600:]}")
    gates["acceptance"] = fails
    # Gate jobs are extra repo-declared checks, so they run only after acceptance
    # is green and while the planner's acceptance bytes are still in the worktree.
    if not fails and repo.gate_jobs:
        gates.update(gatejobs.run_jobs(repo.gate_jobs, wt, wrap))
    git(wt, "checkout", "-q", "--", ".", check=False)
    return gates


# ---------------------------------------------------------------- integration

def candidates(log: EventLog, repo_name: str | None = None) -> list[dict]:
    events = log.read()
    items = project_items(events)
    rels = {r.id: r for r in load_releases()}
    out = []
    for v in items.values():
        if v.state not in ("candidate", "in-train") or v.item_id not in rels:
            continue
        if repo_name and rels[v.item_id].repo != repo_name:
            continue
        a = v.attempts[-1]
        out.append({"item_id": v.item_id, "attempt_id": a["attempt_id"], "branch": a["branch"],
                    "model": a["model"], "repo": rels[v.item_id].repo, "title": rels[v.item_id].title})
    return out


def _merge_failure_reason(p: subprocess.CompletedProcess) -> str:
    """The last non-empty stderr line is the hook's own complaint, not git's noise."""
    lines = [ln.strip() for ln in p.stderr.splitlines() if ln.strip()]
    return f"merge failed: {(lines[-1] if lines else '')[:200]}"


def _train_command(repo, checkout: Path, command: str):
    """Apply the reviewed repository's train boundary, never silently fall back."""
    from .config import home
    if repo.train_isolation == 'environment':
        if _coordinated(repo.name):
            return subprocess.CompletedProcess(command, 1, '', 'coordinated execution requires namespace train isolation')
        try:
            return subprocess.run(command, shell=True, cwd=checkout, capture_output=True, text=True,
                                  env=sandboxing.transport_environment(), timeout=1800)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return subprocess.CompletedProcess(command, 1, '', f'train command failed: {type(exc).__name__}')
    sb = sandboxing.for_train(readonly=(str(state_dir().resolve()), str(home().resolve()),
                                       str(Path(repo.path).resolve())),
                              writable=(str(checkout.resolve()),), timeout_s=1800)
    try:
        return subprocess.run(sb.wrap_shell(command, checkout), shell=True, cwd=checkout,
                              capture_output=True, text=True,
                              env=sandboxing.transport_environment(), timeout=1830)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(command, 1, '', f'train isolation failed: {type(exc).__name__}')


@contextmanager
def _historical_checkout(repo, checkout, tip):
    """Never grant candidate checks writable access to the canonical checkout."""
    if checkout.exists() and checkout.resolve() != Path(repo.path).resolve():
        yield checkout
        return
    with tempfile.TemporaryDirectory(prefix="lanectl-historical-train-") as folder:
        scratch = Path(folder) / 'checkout'
        git(repo.path, 'worktree', 'add', '--detach', '-q', str(scratch), tip)
        try:
            yield scratch
        finally:
            _discard(repo, scratch)


def build_train(log: EventLog, repo_name: str, attempt_ids: list[str] | None = None) -> str:
    repo = load_repos()[repo_name]
    cands = [c for c in candidates(log, repo_name) if not attempt_ids or c["attempt_id"] in attempt_ids]
    if not cands:
        return "no candidates"
    train_id = "train-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    base = git(repo.path, "rev-parse", repo.main)
    wt = repo.worktree_root / train_id
    git(repo.path, "worktree", "add", "-q", "-b", f"train/{train_id}", str(wt), base)
    # Hooks run exactly as git configures them (repo-local core.hooksPath, else the
    # global one, else .git/hooks); never --no-verify and never overridden, so a
    # global secret scan stays in force and a rejection is reported as such.
    g = ["git", "-C", str(wt), *BOT]
    # A fresh worktree has no .venv, but hooks run from it and expect the tools
    # setup_cmd installs; run setup before the first merge as well as after the
    # merges, since candidates may change dependencies.  A setup failure here
    # excludes nothing: the merges proceed and any hook failure is reported.
    if repo.setup_cmd:
        _train_command(repo, wt, repo.setup_cmd)
    included, excluded = [], []
    for c in cands:
        subject = f"Merge lane/{c['attempt_id']}: {c['title']}"
        # Stop before committing so commit-msg sees the subject and its stderr is the
        # real reason; a git-style "Merge ..." subject is what such hooks accept.
        p = subprocess.run([*g, "merge", "--no-ff", "--no-commit", "-q", c["branch"]],
                           capture_output=True, text=True)
        if p.returncode:
            unmerged = git(wt, "diff", "--name-only", "--diff-filter=U", check=False)
            git(wt, "merge", "--abort", check=False)
            reason = "merge conflict" if unmerged else _merge_failure_reason(p)
            excluded.append({"attempt_id": c["attempt_id"], "reason": reason})
            continue
        if git(wt, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False):
            q = subprocess.run([*g, "commit", "-q", "-m", subject], capture_output=True, text=True)
            if q.returncode:
                git(wt, "merge", "--abort", check=False)
                excluded.append({"attempt_id": c["attempt_id"],
                                 "reason": _merge_failure_reason(q)})
                continue
        included.append(c["attempt_id"])
    setup = _train_command(repo, wt, repo.setup_cmd) if repo.setup_cmd else None
    checked_sha = git(wt, "rev-parse", "HEAD")
    p = setup if setup is not None and setup.returncode else _train_command(repo, wt, repo.check_cmd)
    passed = (p.returncode == 0 and bool(included)
              and git(wt, "rev-parse", "HEAD") == checked_sha
              and not git(wt, "status", "--porcelain", "--untracked-files=no"))
    log.append("train.built", {"train_id": train_id, "repo": repo_name, "base_sha": base,
               "attempts": included, "excluded": excluded, "passed": passed,
               "worktree": str(wt), "checked_sha": checked_sha, "check_tail": (p.stdout + p.stderr)[-800:]})
    return (f"{train_id}: {'PASSED' if passed else 'FAILED'} included={included} excluded={excluded}\n"
            f"worktree: {wt}\n{(p.stdout + p.stderr)[-800:]}")


def _serialized_landing(fn):
    @functools.wraps(fn)
    def serialized(log, train_id):
        with log.locked():
            return fn(log, train_id)
    return serialized


@_serialized_landing
def land(log: EventLog, train_id: str) -> str:
    """Judgment-plane action: fast-forward main to the train. Integrator fix commits
    on the train branch must be titled `fix(<attempt_id>): [<fix_class>] ...`."""
    events = log.read()
    tb = next((e for e in reversed(events) if e["type"] == "train.built" and e["data"]["train_id"] == train_id), None)
    if tb is None:
        return f"unknown train {train_id}"
    d = tb["data"]
    recorded = {e["data"]["attempt_id"] for e in events
                if e["type"] == "item.landed" and e["data"]["train_id"] == train_id}
    if d["attempts"] and set(d["attempts"]) <= recorded:
        return f"landed {d['attempts']} (already recorded); use work reconcile for pending completion"
    if not d.get("passed"):
        return f"{train_id}: failed train; rebuild and pass its checks before landing"
    repos = load_repos()
    repo = repos[d["repo"]]
    tip = git(repo.path, "rev-parse", f"train/{train_id}")
    if d.get("checked_sha") and d["checked_sha"] != tip:
        return f"{train_id}: checked tip changed; recheck the train before landing"
    if not d.get("checked_sha"):
        # Historical records predate commit-bound checks. Requalify rather than
        # treating a historical pass as evidence for an arbitrary current tip.
        checkout = Path(d["worktree"])
        if not checkout.exists() and tip != git(repo.path, "rev-parse", repo.main):
            return f"{train_id}: missing checked tip; rebuild the train"
        with _historical_checkout(repo, checkout, tip) as checkout:
            if (git(checkout, "rev-parse", "HEAD") != tip
                    or git(checkout, "status", "--porcelain", "--untracked-files=no")):
                return f"{train_id}: historical worktree differs from train tip; rebuild"
            setup = _train_command(repo, checkout, repo.setup_cmd) if repo.setup_cmd else None
            checked = setup if setup is not None and setup.returncode else _train_command(repo, checkout, repo.check_cmd)
            if (checked.returncode or git(checkout, "rev-parse", "HEAD") != tip
                    or git(checkout, "status", "--porcelain", "--untracked-files=no")):
                return f"{train_id}: failed recheck; not landing"
        d = dict(d, checked_sha=tip)
        log.append("train.built", d)
    requires_deploy = repo.deploy is not None
    deployed = deploy.live(events).get(train_id)
    if requires_deploy:
        expires = capacity.parse_ts(deployed.get("expires_at")) if deployed else None
        if (not deployed or expires is None or expires <= datetime.now(timezone.utc)
                or deployed.get("checked_sha") != tip):
            return (f"{train_id}: repo {repo.name} declares a deploy; run "
                    f"`lanectl deploy run {train_id}` and pass its health check for this tip before landing")
    if git(repo.path, "rev-parse", repo.main) not in (d["base_sha"], tip):
        return f"{repo.main} moved since {train_id} was built; rebuild the train"
    fixes = {}
    recorded_fixes = {(e["data"]["attempt_id"], e["data"]["commit"])
                      for e in events if e["type"] == "integrator.fix"
                      and e["data"].get("train_id") == train_id}
    for line in git(repo.path, "log", "--format=%H %s", f"{d['base_sha']}..{tip}").splitlines():
        sha, subj = line.split(" ", 1)
        if subj.startswith("fix(") and "): [" in subj:
            aid = subj[4:subj.index(")")]
            cls = subj[subj.index("[") + 1:subj.index("]")]
            fixes.setdefault(aid, []).append(sha)
            if (aid, sha) not in recorded_fixes:
                log.append("integrator.fix", {"attempt_id": aid, "commit": sha, "fix_class": cls,
                                              "train_id": train_id})
    guard = getattr(_owner_context, "guard", None)
    if _coordinated(repo.name) and guard is None:
        return f"{train_id}: owner lease required before coordinated landing"
    if guard is not None:
        guard.assert_active()
    cur = git(repo.path, "branch", "--show-current", check=False)
    if cur == repo.main:
        if git(repo.path, "status", "--porcelain", "--untracked-files=no"):
            return f"{repo.path} has tracked changes on {repo.main}; refusing to land"
        git(repo.path, "merge", "--ff-only", "-q", tip)
    else:
        git(repo.path, "update-ref", f"refs/heads/{repo.main}", tip, d["base_sha"])
    by_attempt = {a["attempt_id"]: a["item_id"] for v in project_items(events).values() for a in v.attempts}
    releases = {r.id: r for r in load_releases()}
    already = {e["data"]["attempt_id"] for e in events if e["type"] == "item.landed" and e["data"]["train_id"] == train_id}
    for aid in d["attempts"]:
        if aid in already:
            continue
        rel = releases.get(by_attempt[aid])
        request = ({k: getattr(rel, k) for k in ("id", "repo", "work", "work_complete")} if rel is not None else {})
        log.append("item.landed", {"attempt_id": aid, "train_id": train_id,
                                   "fix_commits": fixes.get(aid, []), "landed_sha": tip, "work_request": request,
                                   "owner_checks": [{"name": "train", "status": "passed", "ref": f"lanectl:{train_id}:{tip}"}]}, item_id=by_attempt[aid])
    # The land is done; the tracker note/close is best effort and never fails it.
    releases = {r.id: r for r in load_releases()}
    for aid in d["attempts"]:
        if aid in already:
            continue
        rel = releases.get(by_attempt[aid])
        if rel is None or not rel.work:
            continue
        try:
            synced = work.sync(rel, train_id, tip, repos)
            if synced is not None:
                log.append("work.synced", synced, item_id=rel.id)
        except Exception as exc:      # retain failed effects for retry
            log.append("work.synced", {"work": rel.work, "train_id": train_id,
                       "closed": False, "ok": False, "error": str(exc)[-300:]}, item_id=rel.id)
    if requires_deploy:
        deploy.teardown(log, train_id, "landed")
    _discard(repo, Path(d["worktree"]))
    for aid in d["attempts"]:
        _discard(repo, repo.worktree_root / aid)
    return f"landed {d['attempts']} on {repo.main} at {tip[:12]}; fixes={ {k: len(v) for k, v in fixes.items()} }"


def approve(log: EventLog, attempt_id: str, note: str) -> str:
    """Judgment plane: accept a parked review-required attempt into the candidate pool."""
    items = project_items(log.read())
    v = next((v for v in items.values() if v.attempts and v.attempts[-1]["attempt_id"] == attempt_id), None)
    if v is None or v.state != "parked":
        return f"{attempt_id}: not the latest attempt of a parked item"
    log.append("decision.recorded", {"attempt_id": attempt_id, "decision": "candidate",
               "reasons": [f"interactive review: {note}"], "rules_revision": "integrator",
               "by": "integrator"}, item_id=v.item_id)
    # The gates only evaluate when they decide candidate, so an approved park has none;
    # without one, landing.plan_landing plans a hold for it.  Idempotent: an evaluation
    # recorded earlier is kept as-is.
    evaluator.evaluate_attempt(log, attempt_id, _evaluator_rules())
    decisions.acceptance_applied(
        log, item_id=v.item_id, attempt_id=attempt_id,
        proposal_id=decisions.latest_acceptance_proposal(log.read(), attempt_id))
    return f"{attempt_id}: candidate (approved)"


def _evaluator_rules() -> dict:
    """Planner rules, or the evaluator's default when no policy is installed.

    ``evaluator.evaluate_attempt`` declines to predict without
    ``governance/evaluator.toml``.  An approval is a ruling in its own right, so
    it still freezes the default verdict (``evaluator/v0``) rather than leaving
    the attempt unevaluated.
    """
    try:
        return evaluator.load_rules()
    except (OSError, tomllib.TOMLDecodeError):
        return {"revision": 0, "default": "accept", "rules": []}


def integrator_reject(log: EventLog, attempt_id: str, reason: str, park: bool = False) -> str:
    items = project_items(log.read())
    v = next((v for v in items.values() if any(a["attempt_id"] == attempt_id for a in v.attempts)), None)
    if v is None:
        return f"unknown attempt {attempt_id}"
    log.append("decision.recorded", {"attempt_id": attempt_id, "decision": "parked" if park else "rejected",
               "reasons": [reason], "rules_revision": "integrator", "by": "integrator"}, item_id=v.item_id)
    log.append("item.parked" if park else "item.requeued", {"reason": reason}, item_id=v.item_id)
    decisions.follow_applied(
        log, item_id=v.item_id, attempt_id=attempt_id,
        follow="park" if park else "requeue",
        mechanism=decisions.MECHANISM_INTEGRATOR, reasons=[reason])
    return f"{attempt_id}: {'parked' if park else 'requeued'}"


# ---------------------------------------------------------------- metrics

def metrics(events: list[dict]) -> dict:
    """Precision = gate-accepted attempts that landed with no integrator fix,
    over gate-accepted attempts the integrator has ruled on.

    Gate acceptance and ruling come from report.py's shared attribution, so an
    attempt the gates parked as review-required and the integrator then approved
    counts here exactly as it does in the report.  ``model_precision`` uses the
    same attribution rule: only fixes classed ``model-error`` count against the
    model, while spec gaps are the planner's and gate gaps the gates'.
    ``fix_classes`` counts integrator fixes by class."""
    attributed = report.attribution(events)
    gate_ok = attributed["gate_ok"]
    ruled = attributed["ruled"]
    landed = set(attributed["landed"])
    landed_clean = attributed["clean"]
    model_clean = attributed["model_clean"]
    attempt_model = {}
    per_model = {}
    for e in events:
        d = e["data"]
        if e["type"] == "experiment.recorded":
            attempt_model[d["attempt_id"]] = d["model"]
            m = per_model.setdefault(d["model"], {"attempts": 0, "candidate": 0, "rejected": 0,
                                                  "parked": 0, "elapsed_s": 0.0})
            m["attempts"] += 1
            m[d["decision"]] = m.get(d["decision"], 0) + 1
            m["elapsed_s"] += d["elapsed_s"]
    for model, m in per_model.items():
        ids = [aid for aid, mod in attempt_model.items() if mod == model]
        model_ruled = sum(1 for aid in ids if aid in ruled)
        model_clean_ruled = sum(1 for aid in ids if aid in model_clean and aid in ruled)
        m["model_precision"] = (round(model_clean_ruled / model_ruled, 3)
                                if model_ruled else None)
        classes = {}
        for aid in ids:
            for cls, n in attributed["fixes"].get(aid, {}).items():
                classes[cls] = classes.get(cls, 0) + n
        m["fix_classes"] = classes
    # ``gate_accepted`` counts every gate-accepted attempt, including ones the
    # integrator has not ruled on yet; ``ruled`` is the precision population.
    return {"gate_accepted": len(gate_ok), "ruled": len(ruled), "landed": len(landed),
            "landed_clean": len(landed_clean),
            "precision": round(len(landed_clean & gate_ok) / len(ruled), 3) if ruled else None,
            "model_precision": (round(len(model_clean & ruled) / len(ruled), 3)
                                if ruled else None),
            "fix_classes": attributed["fix_classes"],
            "per_model": per_model}


def recheck_train(log: EventLog, train_id: str) -> str:
    """Requalify an existing train after bounded judgment-plane fixes."""
    with log.locked():
        built = next((e['data'] for e in reversed(log.read())
                      if e['type'] == 'train.built' and e['data']['train_id'] == train_id), None)
        if built is None:
            return f'{train_id}: unknown train'
        repo = load_repos()[built['repo']]
        checkout = Path(built['worktree'])
        if not checkout.exists():
            return f'{train_id}: train worktree missing; rebuild'
        tip = git(repo.path, 'rev-parse', f'train/{train_id}')
        if (git(checkout, 'rev-parse', 'HEAD') != tip
                or git(checkout, 'status', '--porcelain', '--untracked-files=no')):
            log.append('train.built', dict(built, passed=False, checked_sha=None,
                       check_tail='worktree differs from train tip or has tracked changes'))
            return f'{train_id}: dirty or mismatched worktree; not checked'
        setup = _train_command(repo, checkout, repo.setup_cmd) if repo.setup_cmd else None
        p = setup if setup is not None and setup.returncode else _train_command(repo, checkout, repo.check_cmd)
        passed = (p.returncode == 0 and git(checkout, 'rev-parse', 'HEAD') == tip
                  and git(repo.path, 'rev-parse', f'train/{train_id}') == tip
                  and not git(checkout, 'status', '--porcelain', '--untracked-files=no'))
        log.append('train.built', dict(built, passed=passed, checked_sha=tip,
                   check_tail=(p.stdout + p.stderr)[-800:]))
        return f"{train_id}: {'PASSED' if passed else 'FAILED'} recheck at {tip}"
