"""Direct dev deploys for passed trains (s3-train-deploy).

A repo declares ``[repos.<name>.deploy]`` in governance: the command that brings
a train up, a health check, a teardown command, a TTL and the only environment
variables the deploy may inherit.  Everything else in the operator's environment
(forge tokens, tracker credentials, kubeconfigs) is stripped before a command
runs.  Deploys are recorded as ``train.deployed`` and ``train.torn_down``.
``lanectl deploy list`` shows the live ones; ``reap`` tears down those that
landed, were superseded by a later deploy of their repo, or passed their TTL.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .capacity import parse_ts
from .config import DeploySpec, load_repos
from .events import EventLog

TIMEOUT_S = 1800
TAIL_CHARS = 800


def namespace(train_id: str) -> str:
    """The throwaway dev namespace a train deploys into."""
    return f"lane-dev-{train_id}"


def deploy_env(spec: DeploySpec, train_id: str) -> dict[str, str]:
    """The stripped environment: allow-listed variables plus the LANE_ vars."""
    env = {name: os.environ[name] for name in spec.env_allow if name in os.environ}
    env.update(LANE_NAMESPACE=namespace(train_id), LANE_TRAIN_ID=train_id,
               LANE_TTL_S=str(spec.ttl_s))
    return env


def _latest_built(events: list[dict], train_id: str) -> dict | None:
    for ev in reversed(events):
        if ev.get("type") == "train.built" and (ev.get("data") or {}).get("train_id") == train_id:
            return ev["data"]
    return None


def _expires_at(ttl_s: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=ttl_s)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(cmd: str, cwd: Path, env: dict[str, str]) -> tuple[int, str]:
    """Run one deploy stage in its own process group; return (exit, combined output)."""
    try:
        p = subprocess.run(cmd, shell=True, cwd=cwd, env=env, capture_output=True,
                           text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        out = "".join(part if isinstance(part, str) else (part or b"").decode("utf-8", "replace")
                      for part in (exc.stdout, exc.stderr))
        return 124, f"{out}\ntimed out after {TIMEOUT_S}s"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _spec_for(log: EventLog, train_id: str):
    """(train.built data, repo, DeploySpec) for a known train, else None."""
    built = _latest_built(log.read(), train_id)
    if built is None:
        return None
    repo = load_repos().get(built.get("repo"))
    if repo is None or repo.deploy is None:
        return built, repo, None
    return built, repo, repo.deploy


def deploy_train(log: EventLog, train_id: str) -> str:
    """Deploy a passed train; return a human message and record the outcome."""
    found = _spec_for(log, train_id)
    if found is None:
        return f"unknown train {train_id}"
    built, repo, spec = found
    if not built.get("passed"):
        return f"{train_id}: train did not pass its check; not deploying"
    if spec is None:
        return f"{train_id}: repo {built.get('repo')} declares no deploy"
    ns = namespace(train_id)
    env = deploy_env(spec, train_id)
    worktree = Path(built["worktree"]).resolve()
    for stage, cmd in (("deploy", spec.cmd), ("health", spec.health_cmd)):
        rc, output = _run(cmd, worktree, env)
        if rc == 0:
            continue
        log.append("train.deployed", {
            "train_id": train_id, "repo": repo.name, "namespace": ns, "passed": False,
            "expires_at": _expires_at(spec.ttl_s), "stage": stage,
            "tail": output[-TAIL_CHARS:]})
        teardown(log, train_id, "deploy-failed")
        return (f"{train_id}: {stage} failed (exit {rc}); torn down\n"
                f"{output[-TAIL_CHARS:]}")
    expires_at = _expires_at(spec.ttl_s)
    log.append("train.deployed", {
        "train_id": train_id, "repo": repo.name, "namespace": ns, "passed": True,
        "expires_at": expires_at})
    return f"{train_id}: deployed to {ns} (expires {expires_at})"


def teardown(log: EventLog, train_id: str, reason: str) -> str:
    """Run the repo's teardown command and record a ``train.torn_down`` event."""
    found = _spec_for(log, train_id)
    if found is None:
        # A deploy whose train.built is not in this log: the deploy event still
        # names the repo, so its declared teardown command is reachable.
        data = live(log.read()).get(train_id) or {}
        repo = load_repos().get(data.get("repo"))
        if repo is not None:
            found = None, repo, repo.deploy
    if found is None:
        return f"unknown train {train_id}"
    _, repo, spec = found
    if spec is None:
        return f"{train_id}: repo declares no deploy"
    env = deploy_env(spec, train_id)
    rc, output = _run(spec.teardown_cmd, repo.path, env)
    log.append("train.torn_down", {
        "train_id": train_id, "namespace": namespace(train_id), "reason": reason,
        "passed": rc == 0})
    if rc == 0:
        return f"{train_id}: torn down ({reason})"
    return f"{train_id}: teardown failed (exit {rc}, {reason})\n{output[-TAIL_CHARS:]}"


def live(events: list[dict]) -> dict[str, dict]:
    """Passed deploys that have not been torn down since, keyed by train id."""
    out: dict[str, dict] = {}
    for ev in events:
        etype = ev.get("type")
        data = ev.get("data") or {}
        train_id = data.get("train_id")
        if etype == "train.deployed" and data.get("passed"):
            out[train_id] = data
        elif etype == "train.torn_down" and train_id in out:
            del out[train_id]
    return out


def _expired(data: dict, now: datetime) -> bool:
    expires = parse_ts(data.get("expires_at"))
    return expires is not None and expires <= now


def due(events: list[dict], now: datetime) -> list[tuple[str, str]]:
    """Live deploys to reap, in ``train.deployed`` order, with their reason.

    An item that landed names the train (``landed``); a later passed deploy of
    the same repo replaces it (``superseded``); otherwise it is ``expired`` when
    its ``expires_at`` has passed.  Live deploys in none of those classes are
    not listed.
    """
    now = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    deploys = live(events)
    landed = {((ev.get("data") or {}).get("train_id"))
              for ev in events if ev.get("type") == "item.landed"}
    last_deploy_at: dict[str, int] = {}
    repo_of: dict[str, str] = {}
    for i, ev in enumerate(events):
        data = ev.get("data") or {}
        if ev.get("type") == "train.deployed" and data.get("passed"):
            last_deploy_at[data.get("train_id")] = i
            repo_of[data.get("train_id")] = data.get("repo")
    out: list[tuple[str, str]] = []
    passed = [(i, (ev.get("data") or {}).get("repo")) for i, ev in enumerate(events)
              if ev.get("type") == "train.deployed" and (ev.get("data") or {}).get("passed")]
    for train_id, data in deploys.items():
        at = last_deploy_at.get(train_id, -1)
        later = any(repo == repo_of.get(train_id) and i > at for i, repo in passed)
        if train_id in landed:
            out.append((train_id, "landed"))
        elif later:
            out.append((train_id, "superseded"))
        elif _expired(data, now):
            out.append((train_id, "expired"))
    return out


def reap(log: EventLog, now: datetime | None = None) -> list[str]:
    """Tear down every due deploy and return one line per teardown."""
    now = now or datetime.now(timezone.utc)
    return [teardown(log, train_id, reason) for train_id, reason in due(log.read(), now)]


def list_deploys(events: list[dict], now: datetime | None = None) -> list[dict]:
    """One row per live deploy, with whether it is past its ``expires_at``."""
    now = now or datetime.now(timezone.utc)
    now = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    return [{"train_id": train_id,
             "namespace": data.get("namespace") or namespace(train_id),
             "repo": data.get("repo"), "expires_at": data.get("expires_at"),
             "expired": _expired(data, now)}
            for train_id, data in live(events).items()]


def register(sub) -> dict:
    p = sub.add_parser("deploy", help="run, list or tear down a train's dev deploy")
    actions = p.add_subparsers(dest="deploy_action", required=True)
    run = actions.add_parser("run", help="deploy a passed train and health-check it")
    run.add_argument("train_id")
    down = actions.add_parser("down", help="tear a train's dev deploy down")
    down.add_argument("train_id")
    listed = actions.add_parser("list", help="list live dev deploys")
    listed.add_argument("--json", action="store_true", help="emit the list as JSON")
    actions.add_parser("reap", help="tear down landed, superseded or expired deploys")
    return {"deploy": _cmd}


def _cmd(args, log: EventLog) -> int:
    if args.deploy_action == "down":
        print(teardown(log, args.train_id, "manual"))
        return 0
    if args.deploy_action == "list":
        rows = list_deploys(log.read())
        if not rows:
            print("no live deploys")
        elif args.json:
            print(json.dumps(rows))
        else:
            for row in rows:
                line = (f"{row['namespace']}  {row['train_id']}  {row['repo']}  "
                        f"expires {row['expires_at']}")
                print(line + ("  EXPIRED" if row["expired"] else ""))
        return 0
    if args.deploy_action == "reap":
        lines = reap(log)
        print("\n".join(lines) if lines else "nothing to reap")
        return 0
    print(deploy_train(log, args.train_id))
    last = None
    for ev in log.read():
        data = ev.get("data") or {}
        if ev.get("type") == "train.deployed" and data.get("train_id") == args.train_id:
            last = data
    return 0 if (last is not None and last.get("passed")) else 1
