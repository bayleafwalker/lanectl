"""Delivery loop: claim -> isolate -> implement -> gate -> decide -> record.

Also builds candidate trains and lands them. Scheduling and admission are
deterministic; no agent chooses what runs next.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import adapters, sandbox as sandboxing
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


def pick_model(rel: WorkRelease, lane: LaneRevision, view: ItemView) -> str | None:
    weights = eligible_models(rel, lane)
    if lane.retry == "different_model":
        untried = {m: w for m, w in weights.items() if m not in view.models_tried}
        weights = untried or weights
    weights = {m: w for m, w in weights.items() if w > 0}
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


def admit(lane_name: str, log: EventLog, only: str | None = None) -> Claim | str:
    """Return a Claim, or a string saying why nothing was admitted."""
    lane, repos, releases = load_lane(lane_name), load_repos(), load_releases()
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
        if running >= lane.caps["concurrency"]:
            return f"cap: concurrency {running}/{lane.caps['concurrency']}"
        if claimed_today >= lane.caps["items_per_day"]:
            return f"cap: items_per_day {claimed_today}/{lane.caps['items_per_day']}"
        if unlanded >= lane.caps["accepted_unlanded_max"]:
            return f"cap: accepted_unlanded {unlanded}/{lane.caps['accepted_unlanded_max']} (integrate first)"
        skipped = []
        for rel in releases:
            if only and rel.id != only:
                continue
            v = items[rel.id]
            if v.state not in ("ready", "requeued"):
                continue
            if attempts_used(v, rel.revision) >= lane.max_attempts:
                continue
            reasons = readiness(rel, lane, repos)
            if reasons:
                skipped.append(f"{rel.id}: {'; '.join(reasons)}")
                continue
            model = pick_model(rel, lane, v)
            if model is None:
                skipped.append(f"{rel.id}: no eligible model")
                continue
            n = len(v.attempts) + 1
            attempt_id = f"{rel.id}-a{n}"
            worker = adapters.worker_for(model)
            log.append("item.claimed", {
                "attempt_id": attempt_id, "lane": lane.lane, "lane_revision": lane.revision,
                "lane_digest": lane.digest, "model": model, "worker": worker,
                "release_revision": rel.revision, "base_sha": rel.base_sha,
                "branch": f"lane/{attempt_id}"}, item_id=rel.id)
            return Claim(rel, repos[rel.repo], lane, attempt_id, model, worker)
        return "nothing ready" + ("".join(f"\n  not ready: {s}" for s in skipped))


# ---------------------------------------------------------------- execution

def render_prompt(rel: WorkRelease, lane: LaneRevision) -> str:
    bullets = lambda xs: "\n".join(f"- {x}" for x in xs) or "- (none)"
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
- Do not touch: {", ".join(lane.protected_paths)} (except paths your write scope names explicitly;
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


def execute(c: Claim, log: EventLog, adapter_fn=None) -> str:
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
    sb = sandboxing.from_lane(lane.sandbox, (str(wt),), lane.timeout_s + 120)
    acc = _copy_acceptance(rel, wt)
    seed_sha = _commit_all(wt, f"lane(acceptance): {rel.id} r{rel.revision}")
    if repo.setup_cmd:
        subprocess.run(repo.setup_cmd, shell=True, cwd=wt, capture_output=True)

    runs = state_dir() / "runs"
    runs.mkdir(exist_ok=True)
    shims = sb.shim_dir(state_dir() / "shims" / c.attempt_id, ("opencode", "codex", "claude"))
    env = dict(os.environ, PATH=f"{shims}{os.pathsep}{os.environ.get('PATH', '')}") if shims else None
    main_before = _main_fingerprint(repo)
    started = time.monotonic()
    fn = adapter_fn or adapters.ADAPTERS[c.worker]
    try:
        res = fn(model=c.model, worktree=wt, prompt=render_prompt(rel, lane),
                 status_file=runs / f"{c.attempt_id}.json", timeout_s=lane.timeout_s,
                 external=c.model in lane.external_models, env=env)
    except Exception as exc:  # adapter crash is an attempt outcome, not a runner crash
        res = adapters.AdapterResult("failed", 1, f"adapter error: {exc}", None)
    elapsed = round(time.monotonic() - started, 1)
    breach = _main_fingerprint(repo) != main_before
    # a worker may leave build junk; collect only what git would track
    head = _commit_all(wt, f"lane(attempt): {c.attempt_id} [{c.model}]")
    log.append("attempt.finished", {"attempt_id": c.attempt_id, "outcome": res.outcome,
               "exit_code": res.exit_code, "head_sha": head, "seed_sha": seed_sha,
               "elapsed_s": elapsed, "escalation_reason": res.escalation_reason,
               "final_tail": res.final_tail[-1500:], "isolation_breach": breach}, item_id=rel.id)
    git(repo.path, "fetch", "-q", str(wt), f"+{branch}:{branch}")
    if res.usage:
        log.append("usage.recorded", {"provider": c.worker, "source": "adapter",
                   "units": res.usage, "attempt_id": c.attempt_id, "model": c.model}, item_id=rel.id)

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
    log.append("decision.recorded", {"attempt_id": c.attempt_id, "decision": dec, "reasons": reasons,
               "rules_revision": decision.RULES_REVISION, "by": "gates"}, item_id=rel.id)
    log.append("experiment.recorded", {"attempt_id": c.attempt_id, "model": c.model, "worker": c.worker,
               "task_class": rel.task_class, "size": rel.size, "decision": dec, "elapsed_s": elapsed,
               "lane_revision": lane.revision, "rules_revision": decision.RULES_REVISION,
               "gates_failed": sorted(g for g, vs in gates.items() if vs)}, item_id=rel.id)
    if follow in ("requeue", "requeue-infra"):
        log.append("item.requeued", {"reason": reasons[0] if reasons else dec}, item_id=rel.id)
    elif follow == "park":
        log.append("item.parked", {"reason": "; ".join(reasons)[:500]}, item_id=rel.id)
    if dec != "candidate":
        _discard(repo, wt)
    return f"{c.attempt_id} [{c.model}] -> {dec}: {'; '.join(reasons)[:400]}"


def run_gates(c: Claim, wt: Path, seed_sha: str, head: str, acc: dict[str, bytes],
              worker_outcome: str, sb=None) -> dict[str, list[str]]:
    wrap = sb.wrap_shell if sb else None
    rel, repo, lane = c.rel, c.repo, c.lane
    changes = diffpolicy.collect(wt, seed_sha, head)
    gates = {"diff-policy": diffpolicy.evaluate(changes, rel, lane, rel.acceptance.files)}
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


def build_train(log: EventLog, repo_name: str, attempt_ids: list[str] | None = None) -> str:
    repo = load_repos()[repo_name]
    cands = [c for c in candidates(log, repo_name) if not attempt_ids or c["attempt_id"] in attempt_ids]
    if not cands:
        return "no candidates"
    train_id = "train-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    base = git(repo.path, "rev-parse", repo.main)
    wt = repo.worktree_root / train_id
    git(repo.path, "worktree", "add", "-q", "-b", f"train/{train_id}", str(wt), base)
    included, excluded = [], []
    for c in cands:
        p = subprocess.run(["git", "-C", str(wt), *BOT, "merge", "--no-ff", "-q", "-m",
                            f"train: {c['attempt_id']} {c['title']}", c["branch"]],
                           capture_output=True, text=True)
        if p.returncode:
            git(wt, "merge", "--abort", check=False)
            excluded.append({"attempt_id": c["attempt_id"], "reason": "merge conflict"})
        else:
            included.append(c["attempt_id"])
    if repo.setup_cmd:
        subprocess.run(repo.setup_cmd, shell=True, cwd=wt, capture_output=True)
    p = subprocess.run(repo.check_cmd, shell=True, cwd=wt, capture_output=True, text=True)
    passed = p.returncode == 0 and bool(included)
    log.append("train.built", {"train_id": train_id, "repo": repo_name, "base_sha": base,
               "attempts": included, "excluded": excluded, "passed": passed,
               "worktree": str(wt), "check_tail": (p.stdout + p.stderr)[-800:]})
    return (f"{train_id}: {'PASSED' if passed else 'FAILED'} included={included} excluded={excluded}\n"
            f"worktree: {wt}\n{(p.stdout + p.stderr)[-800:]}")


def land(log: EventLog, train_id: str) -> str:
    """Judgment-plane action: fast-forward main to the train. Integrator fix commits
    on the train branch must be titled `fix(<attempt_id>): [<fix_class>] ...`."""
    events = log.read()
    tb = next((e for e in events if e["type"] == "train.built" and e["data"]["train_id"] == train_id), None)
    if tb is None:
        return f"unknown train {train_id}"
    d = tb["data"]
    repo = load_repos()[d["repo"]]
    if git(repo.path, "rev-parse", repo.main) != d["base_sha"]:
        return f"{repo.main} moved since {train_id} was built; rebuild the train"
    tip = git(repo.path, "rev-parse", f"train/{train_id}")
    fixes = {}
    for line in git(repo.path, "log", "--format=%H %s", f"{d['base_sha']}..{tip}").splitlines():
        sha, subj = line.split(" ", 1)
        if subj.startswith("fix(") and "): [" in subj:
            aid = subj[4:subj.index(")")]
            cls = subj[subj.index("[") + 1:subj.index("]")]
            fixes.setdefault(aid, []).append(sha)
            log.append("integrator.fix", {"attempt_id": aid, "commit": sha, "fix_class": cls,
                                          "train_id": train_id})
    cur = git(repo.path, "branch", "--show-current", check=False)
    if cur == repo.main:
        if git(repo.path, "status", "--porcelain", "--untracked-files=no"):
            return f"{repo.path} has tracked changes on {repo.main}; refusing to land"
        git(repo.path, "merge", "--ff-only", "-q", tip)
    else:
        git(repo.path, "update-ref", f"refs/heads/{repo.main}", tip, d["base_sha"])
    by_attempt = {a["attempt_id"]: a["item_id"] for v in project_items(events).values() for a in v.attempts}
    for aid in d["attempts"]:
        log.append("item.landed", {"attempt_id": aid, "train_id": train_id,
                                   "fix_commits": fixes.get(aid, [])}, item_id=by_attempt[aid])
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
    return f"{attempt_id}: candidate (approved)"


def integrator_reject(log: EventLog, attempt_id: str, reason: str, park: bool = False) -> str:
    items = project_items(log.read())
    v = next((v for v in items.values() if any(a["attempt_id"] == attempt_id for a in v.attempts)), None)
    if v is None:
        return f"unknown attempt {attempt_id}"
    log.append("decision.recorded", {"attempt_id": attempt_id, "decision": "parked" if park else "rejected",
               "reasons": [reason], "rules_revision": "integrator", "by": "integrator"}, item_id=v.item_id)
    log.append("item.parked" if park else "item.requeued", {"reason": reason}, item_id=v.item_id)
    return f"{attempt_id}: {'parked' if park else 'requeued'}"


# ---------------------------------------------------------------- metrics

def metrics(events: list[dict]) -> dict:
    """Precision = gate-accepted attempts that landed with no integrator fix,
    over gate-accepted attempts the integrator has ruled on."""
    gate_ok, landed, landed_clean, int_rejected, per_model = set(), set(), set(), set(), {}
    for e in events:
        d = e["data"]
        if e["type"] == "decision.recorded" and d.get("by") == "gates" and d["decision"] == "candidate":
            gate_ok.add(d["attempt_id"])
        elif e["type"] == "decision.recorded" and d.get("by") == "integrator":
            int_rejected.add(d["attempt_id"])
        elif e["type"] == "item.landed":
            landed.add(d["attempt_id"])
            if not d["fix_commits"]:
                landed_clean.add(d["attempt_id"])
        elif e["type"] == "experiment.recorded":
            m = per_model.setdefault(d["model"], {"attempts": 0, "candidate": 0, "rejected": 0,
                                                  "parked": 0, "elapsed_s": 0.0})
            m["attempts"] += 1
            m[d["decision"]] = m.get(d["decision"], 0) + 1
            m["elapsed_s"] += d["elapsed_s"]
    ruled = (landed | int_rejected) & gate_ok
    return {"gate_accepted": len(gate_ok), "ruled": len(ruled), "landed": len(landed),
            "landed_clean": len(landed_clean),
            "precision": round(len(landed_clean & gate_ok) / len(ruled), 3) if ruled else None,
            "per_model": per_model}
