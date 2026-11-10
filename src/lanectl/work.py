"""Report a landed release to the sprintctl item it delivers (V1).

A land is not finished until the tracker knows: every landed release with a
``work`` reference gets a note on its item carrying the landed commit, and a
release marked ``work_complete`` also closes that item.  A tracker that is down,
misconfigured or slow is reported, never raised: the land itself already
happened, so the failure is recorded as ``work.synced`` with ``ok = false``.

The item reference is ``<repo>#<id>`` (``contracts.WorkRelease.work``); the
repo name selects the checkout sprintctl runs from, because each repo's direnv
environment carries its own tracker credentials.
"""
from __future__ import annotations

import json
import subprocess

DEFAULT_ROOT = "/projects/dev"

# States a not-yet-finished item moves through before it can be closed: sprintctl
# only allows done from active, so pending/blocked are promoted first.
PROMOTE_TO_ACTIVE = ("pending", "blocked")

ERROR_TAIL = 300


def tracker_path(work: str, repos) -> str:
    """The checkout ``work`` reports from: the repo's configured path, else a sibling."""
    name = work.split("#", 1)[0]
    repo = repos[name] if name in repos else None
    if repo is not None:
        return str(repo.path)
    return f"{DEFAULT_ROOT}/{name}"


def _call(run, path: str, sub: list[str]):
    """One sprintctl call through the repo's direnv environment.

    Raises ``_SyncFailed`` with the text worth recording when the call cannot be
    made or exits non-zero.
    """
    cmd = ["direnv", "exec", path, "sprintctl", *sub]
    try:
        p = run(cmd, cwd=path, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    except Exception as exc:      # a missing direnv or a dead tracker is a sync outcome
        raise _SyncFailed(str(exc)) from exc
    if p.returncode != 0:
        tail = (p.stderr or "")[-ERROR_TAIL:]
        raise _SyncFailed(tail or f"sprintctl exited {p.returncode}: {' '.join(sub[:2])}")
    return p


class _SyncFailed(Exception):
    """A sync step failed; the message is what ``work.synced`` carries."""


def _show(run, path: str, work: str) -> dict:
    """The item's ``status`` and ``status_revision`` from ``item show --json``."""
    p = _call(run, path, ["item", "show", "--id", work, "--json"])
    try:
        data = json.loads(p.stdout or "")
    except ValueError as exc:
        raise _SyncFailed(f"item show: not JSON: {exc}") from exc
    item = data.get("item", data) if isinstance(data, dict) else None
    if not isinstance(item, dict) or "status" not in item or "status_revision" not in item:
        raise _SyncFailed("item show: no status/status_revision")
    return item


SERVED_CAS = "direct-backend CAS option"


def _status(run, path: str, work: str, status: str, revision) -> None:
    """Transition with CAS on a direct backend. A served backend refuses
    ``--expected-revision`` (its lifecycle commands carry their own basis), so the
    call is repeated once without it."""
    base = ["item", "status", "--id", work, "--status", status, "--actor", "lanectl"]
    try:
        _call(run, path, [*base, "--expected-revision", str(revision)])
    except _SyncFailed as exc:
        if SERVED_CAS not in str(exc):
            raise
        _call(run, path, base)


def sync(rel, train_id: str, landed_sha: str, repos, run=subprocess.run, *, skip_note=False) -> dict | None:
    """Note (and when ``work_complete``, close) the release's tracker item.

    Returns None when the release has no work reference; otherwise a
    ``work.synced`` payload.  Never raises: the first failing call stops the sync
    and its stderr (or the exception text) is reported as ``error``.
    """
    if not rel.work:
        return None
    result = {"work": rel.work, "train_id": train_id, "closed": False, "ok": True}
    noted = bool(skip_note)
    try:
        path = tracker_path(rel.work, repos)
        if not skip_note:
            _call(run, path, ["item", "note", "--id", rel.work, "--type", "update",
                          "--summary", f"lanectl landed {rel.id} in {train_id}",
                          "--git-sha", landed_sha, "--actor", "lanectl"])
        noted = True
        if not rel.work_complete:
            return result
        repo = repos.get(rel.repo)
        if repo is not None and repo.landing == "pr" and not merged(repo, landed_sha, run):
            result.update(pending_close=True, noted=True)
            return result
        item = _show(run, path, rel.work)
        if item["status"] == "done":
            result["closed"] = True
            return result
        if item["status"] in PROMOTE_TO_ACTIVE:
            _status(run, path, rel.work, "active", item["status_revision"])
            item = _show(run, path, rel.work)
        _status(run, path, rel.work, "done", item["status_revision"])
        result["closed"] = True
    except Exception as exc:      # reported, never raised: the land already happened
        result["ok"] = False
        if noted:
            result["noted"] = True
        result["error"] = str(exc)[-ERROR_TAIL:] or exc.__class__.__name__
    return result


def merged(repo, sha, run=subprocess.run):
    """Refresh the declared canonical main before accepting ancestry as merge proof."""
    def git(*args, allowed=(0,)):
        p = run(["git", "-C", str(repo.path), *args], capture_output=True,
                text=True, stdin=subprocess.DEVNULL)
        if p.returncode not in allowed:
            raise _SyncFailed((p.stderr or "canonical repository check failed")[-ERROR_TAIL:])
        return p
    remote = git("config", "--get", "claude.canonicalRemote", allowed=(0, 1)).stdout.strip() or "origin"
    # Fetch and independent nonempty remote observation prevent a sandboxed empty
    # success from making an old tracking ref look like fresh merge evidence.
    git("fetch", "--no-tags", remote, repo.main)
    advertised = git("ls-remote", "--exit-code", remote, f"refs/heads/{repo.main}").stdout.split()
    head = git("rev-parse", "FETCH_HEAD").stdout.strip()
    if not advertised or len(head) != 40 or advertised[0] != head:
        raise _SyncFailed("canonical main could not be freshly verified")
    return git("merge-base", "--is-ancestor", sha, head, allowed=(0, 1)).returncode == 0


def reconcile(log, *, repos=None, releases=None, run=None):
    """Retry incomplete tracker effects, including PR completion, without relanding."""
    from .config import load_releases, load_repos
    from types import SimpleNamespace
    repos = load_repos() if repos is None else repos
    releases = {r.id: r for r in (load_releases() if releases is None else releases)}
    events = log.read()
    latest = {(e["item_id"], e["data"]["train_id"]): e["data"]
              for e in events if e["type"] == "work.synced"}
    results = []
    for event in events:
        if event["type"] != "item.landed":
            continue
        snapshot = event["data"].get("work_request")
        rel = SimpleNamespace(**snapshot) if snapshot else releases.get(event["item_id"])
        if rel is None or not rel.work:
            continue
        d = event["data"]
        previous = latest.get((rel.id, d["train_id"]), {})
        if previous.get("ok") and (previous.get("closed") or not rel.work_complete):
            continue
        sha = d.get("landed_sha")
        if not sha:
            # Legacy landings lack a stable commit reference. Never guess today's tip.
            results.append({"work": rel.work, "train_id": d["train_id"], "ok": False,
                            "closed": False, "error": "historical landing has no landed_sha"})
            continue
        kwargs = {"skip_note": previous.get("noted", False)}
        if run is not None:
            kwargs["run"] = run
        result = sync(rel, d["train_id"], sha, repos, **kwargs)
        if result is not None:
            log.append("work.synced", result, item_id=rel.id)
            latest[(rel.id, d["train_id"])] = result
            results.append(result)
    return results


def register(sub):
    p = sub.add_parser("work", help="reconcile tracker completion after landing")
    actions = p.add_subparsers(dest="work_action", required=True)
    actions.add_parser("reconcile", help="retry tracker synchronization and pending PR closes")
    return {"work": _cmd}


def _cmd(args, log):
    results = reconcile(log)
    for result in results:
        print(json.dumps(result, sort_keys=True))
    return 1 if any(not r["ok"] for r in results) else 0
