"""Read-only preview of one coordinated claim, plus its guarded execution.

The preview is descriptive: it answers "if the coordinator claimed this
release now, what exactly would it claim and under which configuration?".
It never registers a run, acquires a lease, admits an attempt, writes a log
event or starts a worker.  A digest binds the identity and configuration the
preview saw; ``execute_preview`` re-reads all of it and refuses before
admission if anything moved.  The digest is never authority - admission and
``runner.execute`` remain the only path that creates effects.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json

from . import lifecycle, runner
from .config import load_lane, load_repos, load_releases
from .coordination import CoordinationError, configured
from .ready import readiness

ITEM = "work.public.item-v1"


class PreviewRefused(RuntimeError):
    """A preview was disallowed or became stale.  Never a permission."""


def _now():
    """Wall-clock read time.  Deliberately excluded from the digest."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()


def work_id(release):
    """Return the integer work id from a complete ``repo#id`` ref, or None."""
    work, complete, repo = release.work, release.work_complete, release.repo
    if not work or not complete:
        return None
    owner, _, number = work.partition("#")
    if owner != repo or not number.isdigit() or int(number) <= 0:
        return None
    return int(number)


def _owner(client, item_id):
    """One fresh, catalog-checked item read; never a cached or joined fact."""
    try:
        catalog = client.discover()
        if not isinstance(catalog, dict) or not isinstance(catalog.get("revision"), str):
            raise CoordinationError("invalid owner catalog")
    except CoordinationError as exc:
        return {"revision": None, "value": None, "reason": str(exc)}
    fact = lifecycle._fact(client, catalog, ITEM, {"work_id": item_id})
    if fact.get("state") != "observed":
        return {"revision": catalog["revision"], "value": None,
                "reason": fact.get("reason") or "owner item unavailable"}
    return {"revision": catalog["revision"], "value": fact.get("value"), "reason": None}


def _item(value, item_id):
    """Check the declared owner shape ``{authority,state,as_of,item}``."""
    reasons = []
    if not isinstance(value, dict) or value.get("authority") != "sprintctl" \
            or value.get("state") != "ok" or not isinstance(value.get("as_of"), str):
        reasons.append("owner item response is unavailable or not authoritative")
    item = value.get("item") if isinstance(value, dict) else None
    if not isinstance(item, dict) or not all(
            name in item for name in ("work_id", "status", "resolution")):
        reasons.append("owner item response does not describe one work item")
        return None, reasons
    if isinstance(item["work_id"], bool) or item["work_id"] != item_id:
        reasons.append(f"owner item {item['work_id']!r} is not work {item_id!r}")
    if item["status"] != "pending":
        reasons.append(f"owner item status {item['status']!r} is not pending")
    return {"work_id": item["work_id"], "status": item["status"],
            "resolution": item["resolution"]}, reasons


def _bound(release, lane, repo, owner, item, item_id):
    """Identity and configuration the digest binds; no wall-clock read times."""
    return {
        "work_id": item_id,
        "release": {
            "id": release.id, "repo": release.repo, "revision": release.revision,
            "base_sha": release.base_sha, "work": release.work,
            "work_complete": release.work_complete, "draft": release.draft,
            "size": release.size, "task_class": release.task_class,
            "data_class": release.data_class, "scope_paths": list(release.scope_paths),
            "eligible_lanes": list(release.eligible_lanes),
            "acceptance_exec": list(release.acceptance.exec),
            "acceptance_files": list(release.acceptance.files),
        },
        "lane": {
            "lane": lane.lane, "revision": lane.revision, "digest": lane.digest,
            "size_max": lane.size_max, "routing": lane.routing, "caps": lane.caps,
            "max_attempts": lane.max_attempts, "timeout_s": lane.timeout_s,
            "retry": lane.retry, "size_budget_lines": lane.size_budget_lines,
            "protected_paths": list(lane.protected_paths),
            "dependency_manifests": list(lane.dependency_manifests),
            "test_globs": list(lane.test_globs),
            "forbidden_added_patterns": list(lane.forbidden_added_patterns),
            "allow_restricted": lane.allow_restricted,
            "external_models": list(lane.external_models),
            "sandbox": lane.sandbox, "effects": lane.effects,
        },
        "repo": None if repo is None else {
            "name": repo.name, "path": str(repo.path), "main": repo.main,
            "test_cmd": repo.test_cmd, "check_cmd": repo.check_cmd,
            "worktree_root": str(repo.worktree_root), "setup_cmd": repo.setup_cmd,
            "data_class_floor": repo.data_class_floor, "routing": repo.routing,
            "landing": repo.landing, "train_isolation": repo.train_isolation,
            "protected_paths": list(repo.protected_paths),
            "gate_jobs": [repr(job) for job in repo.gate_jobs],
            "deploy": None if repo.deploy is None else repr(repo.deploy),
        },
        "owner": owner,
        "item": item,
    }


def preview_claim(client, release, lane, repos):
    """Describe what a coordinated claim would do, without doing any of it.

    Allowed requires a fresh owner item read that matches the release, agrees
    the item is pending, a complete ``repo#id`` work ref, a configured
    repository and local readiness.  Owner uncertainty is never allowance.
    """
    item_id = work_id(release)
    repo = repos.get(release.repo)
    reasons = []
    if item_id is None:
        reasons.append(f"release work ref {release.work!r} is not a complete {release.repo}#id ref")
    if repo is None:
        reasons.append(f"repo {release.repo!r} is not in governance/repos.toml")
    reasons.extend(f"release not ready: {reason}" for reason in readiness(release, lane, repos))
    owner = _owner(client, item_id)
    if owner["value"] is None:
        reasons.append(f"owner item unavailable: {owner['reason']}")
    item, item_reasons = _item(owner["value"], item_id)
    reasons.extend(item_reasons)
    bound = _bound(release, lane, repo, {
        "revision": owner["revision"],
        "authority": owner["value"].get("authority") if isinstance(owner["value"], dict) else None,
        "state": owner["value"].get("state") if isinstance(owner["value"], dict) else None,
        "as_of": owner["value"].get("as_of") if isinstance(owner["value"], dict) else None,
    }, item, item_id)
    return {
        "release_id": release.id,
        "repo": release.repo,
        "work_id": item_id,
        "lane": lane.lane,
        "release_revision": release.revision,
        "lane_revision": lane.revision,
        "owner_revision": owner["revision"],
        "observed_at": _now(),
        "allowed": not reasons,
        "reasons": reasons,
        "digest": _digest(bound),
    }


def _client_for(repo_name):
    coordinator = configured(repo_name)
    if coordinator is None:
        raise PreviewRefused(f"{repo_name}: Vuoro coordination is not configured")
    return coordinator.client


def command(preview):
    return (f"lanectl claim-run --item {preview['release_id']} --lane {preview['lane']} "
            f"--execute --expect {preview['digest']}")


def execute_preview(preview, log, *, client=None):
    """Re-read everything, re-check the digest, then use the existing run path.

    Nothing here retries admission or starts a second attempt: an uncertain
    execution is left to the existing durable replay in ``runner.execute``.
    """
    if not isinstance(preview, dict) or not preview.get("release_id") or not preview.get("digest"):
        raise PreviewRefused("a complete preview is required before execution")
    release_id = preview["release_id"]
    try:
        release = next((rel for rel in load_releases() if rel.id == release_id), None)
        lane = load_lane(preview.get("lane") or "")
        repos = load_repos()
    except (OSError, ValueError) as exc:
        raise PreviewRefused(f"configuration unavailable: {exc}") from None
    if release is None:
        raise PreviewRefused(f"release {release_id!r} is no longer available")
    if client is None:
        client = _client_for(release.repo)
    fresh = preview_claim(client, release, lane, repos)
    if not fresh["allowed"]:
        raise PreviewRefused("claim is not allowed: " + "; ".join(fresh["reasons"]))
    if fresh["digest"] != preview["digest"]:
        raise PreviewRefused("preview changed since it was shown; preview again and re-approve the new digest")
    claim = runner.admit(lane.lane, log, only=release_id)
    if isinstance(claim, str):
        return claim
    if claim.rel.id != release_id or claim.rel.revision != release.revision \
            or claim.rel.base_sha != release.base_sha:
        raise PreviewRefused("admission returned a claim for different release content")
    return runner.execute(claim, log)


def render(preview):
    """Terminal text with the exact identity, revisions and next command."""
    lines = [f"release  {preview['release_id']}",
             f"repo     {preview['repo']}",
             f"work     {preview['repo']}#{preview['work_id']}",
             f"lane     {preview['lane']} r{preview['lane_revision']}",
             f"revision {preview['release_revision']}",
             f"owner    {preview['owner_revision']}",
             f"observed {preview['observed_at']}",
             f"digest   {preview['digest']}",
             f"allowed  {'yes' if preview['allowed'] else 'no'}"]
    lines.extend(f"  - {reason}" for reason in preview["reasons"])
    lines.append("execute  " + command(preview))
    return "\n".join(lines)


def register(sub):
    parser = sub.add_parser(
        "claim-run", help="preview one coordinated claim (read-only) or execute an approved preview")
    parser.add_argument("--item", required=True, metavar="RELEASE", help="release id from the backlog")
    parser.add_argument("--lane", default="implement", help="lane name (default implement)")
    parser.add_argument("--json", action="store_true", help="emit the preview as JSON")
    parser.add_argument("--execute", action="store_true",
                        help="claim and run after re-checking the preview digest")
    parser.add_argument("--expect", metavar="DIGEST", help="digest printed by the preview being approved")
    return {"claim-run": _cmd}


def _cmd(args, log, *, client=None):
    """CLI adapter kept thin so tests can inject a fake catalog client."""
    try:
        release = next((rel for rel in load_releases() if rel.id == args.item), None)
        if release is None:
            print(f"{args.item}: no such release")
            return 1
        lane, repos = load_lane(args.lane), load_repos()
        if client is None:
            client = _client_for(release.repo)
        preview = preview_claim(client, release, lane, repos)
        print(json.dumps(preview, sort_keys=True) if args.json else render(preview))
        if not args.execute:
            return 0 if preview["allowed"] else 1
        if not preview["allowed"]:
            print("refusing to execute: the preview is not allowed")
            return 1
        if not args.expect:
            print("refusing to execute without --expect DIGEST")
            return 1
        if args.expect != preview["digest"]:
            print(f"refusing to execute: --expect {args.expect} is not the current digest {preview['digest']}")
            return 1
        print(execute_preview(preview, log, client=client))
        return 0
    except (PreviewRefused, CoordinationError, OSError, ValueError) as exc:
        print(f"claim-run: {exc}")
        return 1
