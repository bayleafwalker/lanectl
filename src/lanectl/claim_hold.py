"""Advanced, owner-bounded claim-only hold with exact recovery.

Claim-and-run stays the default path.  A hold is a separate, advanced action:
it uses the existing owner run registration and lease acquisition, then starts
no worker, so an operator can inspect or hand off the item until the owner's
own lease expiry ends the hold.  There is no local claim event, timer,
heartbeat, forced release/completion, outcome report, landing or second lease
table: everything here goes through the existing coordinator journal.

The preview is descriptive and digest-bound (reason, claim-only mode, release,
lane, repo and owner identity).  The journal keeps the exact request bytes and
the claim-only intent, so a lost acknowledgement is recovered by replaying the
same request identities - never by reacquiring or extending the hold.  A
receipt is one owner observation; cached expiry is never current authority.
The module reuses claim_preview's catalog-checked owner read and digest helpers
so claim-run and claim-hold cannot drift apart.
"""
from __future__ import annotations

import hashlib
import json
import shlex

from . import claim_preview
from .claim_preview import PreviewRefused, work_id
from .config import load_lane, load_repos, load_releases
from .coordination import CoordinationError, configured

MODE = "claim-only"
# The registration is deliberately labelled: no worker or model runs under it,
# and the owner binds it to the exact previewed intent instead.
MODEL = "claim-only"
RECIPE = "lanectl/claim-hold/v1"
EVIDENCE_KEY = "claim-only"
NOTICE = ("one owner lease observation, not continuing authority; the hold ends "
          "through the owner's existing lease expiry policy")


def _now():
    return claim_preview._now()


def _audience(client):
    """Safe owner/principal audience fields; never credentials or tokens."""
    return {"endpoint": getattr(client, "endpoint", None),
            "repo_id": getattr(client, "repo_id", None),
            "environment": getattr(client, "expected_environment", None)}


def _reason(reason):
    if not isinstance(reason, str) or not reason.strip():
        raise PreviewRefused("a claim-only hold requires an explicit non-blank reason")
    return reason


def _claim_id(digest):
    return "hold-" + hashlib.sha256(digest.encode()).hexdigest()[:24]


def preview_hold(client, release, lane, repos, *, reason):
    """Describe one claim-only hold without registering, claiming or writing.

    Allowed requires the same fresh catalog-checked pending owner item, complete
    ``repo#id`` work ref, configured repository and Definition of Ready that
    claim-run requires.  Owner uncertainty is never allowance.
    """
    reason = _reason(reason)
    item_id = work_id(release)
    repo = repos.get(release.repo)
    reasons = [] if item_id is not None else [
        f"release work ref {release.work!r} is not a complete {release.repo}#id ref"]
    # Resolved through claim_preview so both surfaces share one readiness check.
    reasons.extend(f"release not ready: {item}" for item in
                   claim_preview.readiness(release, lane, repos))
    owner = claim_preview._owner(client, item_id)
    if owner["value"] is None:
        reasons.append(f"owner item unavailable: {owner['reason']}")
    item, item_reasons = claim_preview._item(owner["value"], item_id)
    reasons.extend(item_reasons)
    audience = _audience(client)
    bound = claim_preview._bound(release, lane, repo, {
        "revision": owner["revision"],
        "authority": owner["value"].get("authority") if isinstance(owner["value"], dict) else None,
        "state": owner["value"].get("state") if isinstance(owner["value"], dict) else None,
        "endpoint": audience["endpoint"],
        "repo_id": audience["repo_id"],
    }, item, item_id)
    # Only the hold semantics are added; wall-clock read times stay excluded.
    # The environment qualifies the owner/principal the preview was shown against.
    bound["hold"] = {"mode": MODE, "reason": reason, "environment": audience["environment"]}
    return {"release_id": release.id, "repo": release.repo, "work_id": item_id,
            "lane": lane.lane, "release_revision": release.revision,
            "lane_revision": lane.revision, "owner_revision": owner["revision"],
            "observed_at": _now(), "mode": MODE, "reason": reason,
            "allowed": not reasons, "reasons": reasons,
            "digest": claim_preview._digest(bound)}


def _reload(preview):
    """Re-read the approved preview's configuration before its first effect."""
    if not isinstance(preview, dict) or not preview.get("release_id") or not preview.get("digest"):
        raise PreviewRefused("a complete claim-only preview is required")
    if preview.get("mode") != MODE:
        raise PreviewRefused("only a claim-only preview can start a hold")
    reason = _reason(preview.get("reason"))
    try:
        release = next((rel for rel in load_releases() if rel.id == preview["release_id"]), None)
        lane, repos = load_lane(preview.get("lane") or ""), load_repos()
    except (OSError, ValueError) as exc:
        raise PreviewRefused(f"configuration unavailable: {exc}") from None
    if release is None:
        raise PreviewRefused(f"release {preview['release_id']!r} is no longer available")
    return release, lane, repos, reason


def _metadata(preview, release, lane, client):
    """Stable claim-only intent; persisted with the registration, before effects."""
    return {"mode": MODE, "claim_id": _claim_id(preview["digest"]),
            "reason": preview["reason"], "digest": preview["digest"],
            "work_id": preview["work_id"],
            "release": {"id": release.id, "revision": release.revision,
                        "repo": release.repo, "work": release.work,
                        "base_sha": release.base_sha},
            "lane": {"lane": lane.lane, "revision": lane.revision, "digest": lane.digest},
            "owner": _audience(client)}


def _journal_run_id(coordinator, claim_id):
    """Recover the acknowledged run id from the registration journal, or None.

    A lost acquire acknowledgement must not discard the owner link already
    acknowledged and journalled by the registration.  A lost registration
    acknowledgement leaves no stored result, so its run id stays unknown.
    """
    saved = coordinator.saved_request(claim_id + ":run")
    if saved is None or not isinstance(saved[2], dict):
        return None
    run = saved[2].get("run")
    return run.get("run_id") if isinstance(run, dict) else None


def _evidence(coordinator, claim_id, metadata, binding):
    """The one truthful Observation, replayed with its original bytes."""
    saved = coordinator.saved_request(claim_id + ":evidence:" + EVIDENCE_KEY)
    if saved is not None and isinstance(saved[0], dict):
        body = saved[0].get("body")
        if (isinstance(body, dict) and body.get("mode") == MODE
                and body.get("reason") == metadata["reason"]):
            return body
    return {"mode": MODE, "reason": metadata["reason"],
            "release_id": metadata["release"]["id"], "work_id": metadata["work_id"],
            "run_id": binding["run_id"], "expires_at": binding["lease"]["expires_at"],
            "worker_started": False, "observed_at": _now(),
            "intent": "claim-only hold; no worker, heartbeat, outcome or landing"}


def _receipt(coordinator, claim_id, metadata, *, state, observed_at, source, uncertainty=None):
    binding = coordinator.recorded_binding(claim_id) or {}
    lease = binding.get("lease") or {}
    run_id = binding.get("run_id")
    if run_id is None:
        # Registration may already be acknowledged and journalled even though
        # the lease binding is not yet stored; keep that known owner link.
        run_id = _journal_run_id(coordinator, claim_id)
    result = {"state": state, "mode": MODE, "claim_id": claim_id,
              "run_id": run_id, "item_id": metadata["work_id"],
              "release_id": metadata["release"]["id"],
              "expires_at": lease.get("expires_at"), "reason": metadata["reason"],
              "worker_started": False, "source": source,
              "observed_at": observed_at, "notice": NOTICE}
    if uncertainty is not None:
        result["uncertainty"] = uncertainty
    return result


def _advance(coordinator, claim_id, metadata):
    """Acquire once if needed, then finish only the pending evidence append."""
    observed = _now()
    acquired = False
    try:
        binding = coordinator.recorded_binding(claim_id)
        if binding is None:
            # Replays the journal's exact acquire bytes when they exist; an
            # accepted binding is never reacquired.
            binding = coordinator.start(claim_id, metadata["work_id"], MODEL,
                                        metadata["digest"], recipe_id=RECIPE,
                                        metadata=metadata)
            acquired = True
        body = _evidence(coordinator, claim_id, metadata, binding)
        coordinator.append_evidence(claim_id, EVIDENCE_KEY, "Observation", body)
    except CoordinationError as exc:
        return _receipt(coordinator, claim_id, metadata, state="unknown",
                        observed_at=observed, source="lanectl.coordination.journal",
                        uncertainty=str(exc))
    return _receipt(coordinator, claim_id, metadata, state="observed",
                    observed_at=body.get("observed_at") or observed,
                    source="vuoro-owner" if acquired else "lanectl.coordination.journal")


def execute_hold(preview, *, coordinator=None):
    """Re-check the approved preview, then take only its owner claim.

    The fresh checks run before the first mutation; a changed or disallowed
    preview is refused.  Owner uncertainty returns state ``unknown`` with the
    same claim id so ``resume_hold`` can replay exact bytes.
    """
    release, lane, repos, reason = _reload(preview)
    if coordinator is None:
        coordinator = configured(release.repo)
        if coordinator is None:
            raise PreviewRefused(f"{release.repo}: Vuoro coordination is not configured")
    fresh = preview_hold(coordinator.client, release, lane, repos, reason=reason)
    if not fresh["allowed"]:
        raise PreviewRefused("hold is not allowed: " + "; ".join(fresh["reasons"]))
    if fresh["digest"] != preview["digest"]:
        raise PreviewRefused("preview changed since it was shown; preview again and approve the new digest")
    metadata = _metadata(fresh, release, lane, coordinator.client)
    saved = coordinator.saved_metadata(metadata["claim_id"])
    if saved is None and coordinator.saved_request(metadata["claim_id"] + ":run") is not None:
        raise PreviewRefused("this hold id is already journalled with a different intent")
    if saved is not None and saved != metadata:
        raise PreviewRefused("this hold id already records a different claim-only plan")
    return _advance(coordinator, metadata["claim_id"], metadata)


def _validate(metadata, claim_id, client):
    """The saved intent must still be this claim-only hold for this owner."""
    digest = metadata.get("digest")
    if (metadata.get("mode") != MODE or metadata.get("claim_id") != claim_id
            or not isinstance(digest, str) or _claim_id(digest) != claim_id):
        raise PreviewRefused(f"{claim_id}: saved journal entry is not this claim-only hold")
    _reason(metadata.get("reason"))
    work = metadata.get("work_id")
    if not isinstance(work, int) or isinstance(work, bool) or work <= 0:
        raise PreviewRefused(f"{claim_id}: saved hold has no owner work id")
    release = metadata.get("release")
    if not isinstance(release, dict) or not all(
            isinstance(release.get(name), str) and release.get(name)
            for name in ("id", "repo", "work")):
        raise PreviewRefused(f"{claim_id}: saved hold has no release identity")
    if metadata.get("owner") != _audience(client):
        raise PreviewRefused(f"{claim_id}: saved hold belongs to a different owner/principal")


def resume_hold(claim_id, *, coordinator):
    """Replay one existing hold intent; unknown ids mutate nothing.

    A known binding is returned as its last-observed receipt and is never
    reacquired, heartbeated or extended; only a pending evidence append is
    finished.  Cached expiry is not inferred to be current authority.
    """
    if not isinstance(claim_id, str) or not claim_id:
        raise PreviewRefused("a hold id is required")
    try:
        metadata = coordinator.saved_metadata(claim_id)
    except (OSError, ValueError) as exc:
        raise PreviewRefused(f"{claim_id}: journal unavailable: {exc}") from None
    if metadata is None:
        raise PreviewRefused(f"{claim_id}: no saved claim-only hold to resume")
    _validate(metadata, claim_id, coordinator.client)
    return _advance(coordinator, claim_id, metadata)


def command(preview):
    return (f"lanectl claim-hold --item {preview['release_id']} --lane {preview['lane']} "
            f"--reason {shlex.quote(preview['reason'])} --execute --expect {preview['digest']}")


def render(preview):
    lines = [f"release  {preview['release_id']}",
             f"repo     {preview['repo']}",
             f"work     {preview['repo']}#{preview['work_id']}",
             f"lane     {preview['lane']} r{preview['lane_revision']}",
             f"mode     {preview['mode']} (advanced; no worker will start)",
             f"reason   {preview['reason']}",
             f"revision {preview['release_revision']}",
             f"owner    {preview['owner_revision']}",
             f"observed {preview['observed_at']}",
             f"digest   {preview['digest']}",
             f"allowed  {'yes' if preview['allowed'] else 'no'}"]
    lines.extend(f"  - {reason}" for reason in preview["reasons"])
    lines.append("execute  " + command(preview))
    return "\n".join(lines)


def render_result(result):
    expires = result.get("expires_at")
    lines = [f"hold     {result['claim_id']}",
             f"state    {result['state']}",
             f"mode     {result['mode']}",
             f"item     {result['item_id']}",
             f"run      {result['run_id'] or 'unknown'}",
             f"reason   {result['reason']}",
             f"worker   {'started' if result['worker_started'] else 'not started'}",
             f"observed {result['observed_at']}",
             f"source   {result['source']}",
             f"expires  {expires} (UTC owner lease expiry; no local timer)" if expires
             else "expires  unknown (no owner lease observed)",
             f"notice   {result['notice']}"]
    if result.get("uncertainty"):
        lines.append(f"uncertainty {result['uncertainty']}")
        lines.append(f"recover  lanectl claim-hold --repo REPO --resume {result['claim_id']}")
    return "\n".join(lines)


def register(sub):
    parser = sub.add_parser(
        "claim-hold", help="advanced claim-only hold: preview, execute, or resume")
    parser.add_argument("--item", metavar="RELEASE", help="release id from the backlog")
    parser.add_argument("--lane", default="implement", help="lane name (default implement)")
    parser.add_argument("--reason", metavar="TEXT", help="explicit operator reason (required)")
    parser.add_argument("--json", action="store_true", help="emit the preview or receipt as JSON")
    parser.add_argument("--execute", action="store_true",
                        help="take the previewed owner claim and start no worker")
    parser.add_argument("--expect", metavar="DIGEST", help="digest printed by the approved preview")
    parser.add_argument("--repo", metavar="REPO", help="configured owner repository (recovery)")
    parser.add_argument("--resume", metavar="HOLD_ID", help="replay one existing hold intent")
    return {"claim-hold": _cmd}


def _cmd(args, log, *, client=None, coordinator=None):
    """CLI adapter kept thin so tests can inject a client and coordinator."""
    try:
        return _resume(args, coordinator) if args.resume else _preview(args, client, coordinator)
    except (PreviewRefused, CoordinationError, OSError, ValueError) as exc:
        print(f"claim-hold: {exc}")
        return 1


def _resume(args, coordinator):
    if not args.repo:
        print("claim-hold: --resume requires --repo REPO")
        return 1
    coordinator = coordinator or configured(args.repo)
    if coordinator is None:
        print(f"{args.repo}: Vuoro coordination is not configured")
        return 1
    result = resume_hold(args.resume, coordinator=coordinator)
    print(json.dumps(result, sort_keys=True) if args.json else render_result(result))
    return 0 if result["state"] == "observed" else 2


def _preview(args, client, coordinator):
    if not args.item:
        print("claim-hold: --item RELEASE or --resume HOLD_ID is required")
        return 1
    release = next((rel for rel in load_releases() if rel.id == args.item), None)
    if release is None:
        print(f"{args.item}: no such release")
        return 1
    lane, repos = load_lane(args.lane), load_repos()
    if coordinator is None:
        coordinator = configured(release.repo)
        if coordinator is None:
            print(f"{release.repo}: Vuoro coordination is not configured")
            return 1
    preview = preview_hold(client or coordinator.client, release, lane, repos, reason=args.reason)
    print(json.dumps(preview, sort_keys=True) if args.json else render(preview))
    if not args.execute:
        return 0 if preview["allowed"] else 1
    if not preview["allowed"]:
        print("refusing to hold: the preview is not allowed")
        return 1
    if not args.expect:
        print("refusing to hold without --expect DIGEST")
        return 1
    if args.expect != preview["digest"]:
        print(f"refusing to hold: --expect {args.expect} is not the current digest {preview['digest']}")
        return 1
    result = execute_hold(preview, coordinator=coordinator)
    print(json.dumps(result, sort_keys=True) if args.json else render_result(result))
    return 0 if result["state"] == "observed" else 2
