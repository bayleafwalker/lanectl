"""Direct dev deploys for passed trains (s3-train-deploy).

A repo declares ``[repos.<name>.deploy]`` in governance: the command that brings
a train up, a health check, a teardown command, a TTL and the only environment
variables the deploy may inherit.  Everything else in the operator's environment
(forge tokens, tracker credentials, kubeconfigs) is stripped before a command
runs.  Deploys are recorded as ``train.deployed`` and ``train.torn_down``.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


def register(sub) -> dict:
    p = sub.add_parser("deploy", help="run or tear down a train's dev deploy")
    actions = p.add_subparsers(dest="deploy_action", required=True)
    run = actions.add_parser("run", help="deploy a passed train and health-check it")
    run.add_argument("train_id")
    down = actions.add_parser("down", help="tear a train's dev deploy down")
    down.add_argument("train_id")
    return {"deploy": _cmd}


def _cmd(args, log: EventLog) -> int:
    if args.deploy_action == "down":
        print(teardown(log, args.train_id, "manual"))
        return 0
    print(deploy_train(log, args.train_id))
    passed = any(e.get("type") == "train.deployed"
                 and (e.get("data") or {}).get("train_id") == args.train_id
                 and e["data"].get("passed") for e in log.read())
    return 0 if passed else 1
