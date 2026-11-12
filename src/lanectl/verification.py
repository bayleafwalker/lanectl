"""Read-only lifecycle evidence bundles and verification review.

``lanectl.verification`` is a projection, not a second state machine: it joins
the local gate/train/receipt events with fresh owner reads into one explainable
bundle per attempt.  It never mutates a snapshot, writes an event, or contacts
the owner.  Missing, rejected, stale and unknown are first-class so a local
report can never be mistaken for independent acceptance.

Each bundle has ``item_id``, ``attempt_id``, a summary ``outcome`` and an
``entries`` list.  Every entry carries ``kind``, ``state``, provenance
(``source``, ``revision``, ``checkpoint``, ``observed_at``) and safe
``references``.  Provenance is preserved verbatim from the lifecycle fact
groups; owner values are read from ``work.evidence.tail-v1`` and
``work.public.item-v1`` and never altered.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import urlsplit

from .lifecycle import lifecycle_rows

# The fixed set of entry kinds, in display order.
KINDS = ("gates", "checked-commit", "deploy", "landing",
         "evidence-chain", "outcome-report", "owner-decision")

# Entry kinds whose completeness is required for an accepted lifecycle.
LOCAL_KINDS = ("gates", "checked-commit", "deploy", "landing", "outcome-report")

# Only these schemes may appear in a published reference.
_SAFE_SCHEMES = ("https", "lane")


def _fact(row, name):
    facts = row.get("facts", {}) if isinstance(row, dict) else {}
    return facts.get(name, {})


def _group_state(fact):
    if not isinstance(fact, dict):
        return "unknown"
    return fact.get("state", "unknown")


def _provenance(fact):
    if not isinstance(fact, dict):
        fact = {}
    return {"source": fact.get("source"), "revision": fact.get("revision"),
            "checkpoint": fact.get("checkpoint"),
            "observed_at": fact.get("observed_at")}


def _events(fact):
    value = fact.get("value") if isinstance(fact, dict) else None
    return value if isinstance(value, list) else []


def _event_data(event):
    data = event.get("data") if isinstance(event, dict) else None
    return data if isinstance(data, dict) else {}


def _entry(kind, state, fact, references=(), details=None):
    return {"kind": kind, "state": state, **_provenance(fact),
            "references": list(references), "details": dict(details or {})}


def _pick(data, names):
    """Allowlisted event fields; never bodies, violations, tails or transcripts."""
    return {name: data[name] for name in names if name in data and data[name] is not None}


# The only event fields default/evidence inspection may publish.
EVENT_DETAIL_FIELDS = {
    "item.claimed": ("attempt_id", "lane", "model", "worker"),
    "attempt.finished": ("attempt_id", "outcome", "exit_code", "head_sha", "seed_sha"),
    "gate.result": ("attempt_id", "gate", "passed"),
    "decision.recorded": ("attempt_id", "decision"),
    "train.built": ("train_id", "base_sha", "attempts", "passed", "checked_sha"),
    "train.deployed": ("train_id", "repo", "namespace", "passed", "checked_sha", "expires_at"),
    "train.torn_down": ("train_id",),
    "item.landed": ("attempt_id", "train_id", "landed_sha", "fix_commits"),
    "work.synced": ("work", "train_id", "closed", "ok", "owner_reported", "pending_owner"),
    "release.published": ("release_id", "revision"),
}


def _event_details(event):
    data = _event_data(event)
    return {"type": event.get("type"), **_pick(data, EVENT_DETAIL_FIELDS.get(event.get("type"), ()))}


def safe_fact_details(name, fact):
    """Small allowlisted projection for default TUI inspection.

    It deliberately never returns an entire ``fact.value``: raw evidence
    bodies, check tails, violations, transcripts and secrets stay unrendered.
    """
    if not isinstance(fact, dict) or fact.get("state") != "observed":
        return {}
    value = fact.get("value")
    if name in ("local.release", "local.attempt", "local.train", "local.receipt"):
        return {"events": [_event_details(event) for event in _events(fact)
                           if isinstance(event, dict)]}
    if name == "work.public.item-v1" and isinstance(value, dict):
        nested = value.get("item")
        details = _pick(value, ("authority", "state", "as_of"))
        if isinstance(nested, dict):
            details["item"] = _pick(nested, ("work_id", "status", "resolution"))
        elif "state" in value:
            details["item"] = {"status": value.get("state")}
        return details
    if name in ("work.lease.read-v1", "work.run.resolve-v1") and isinstance(value, dict):
        return _pick(value, ("lease", "run"))
    if name == "work.evidence.tail-v1" and isinstance(value, dict):
        item = value.get("item")
        return {"item": _pick(item, ("chain_seq",))} if isinstance(item, dict) else {}
    return {}


def _safe_ref(value):
    """Return *value* only when it is a clean ``https://`` or ``lane://`` locator.

    Userinfo, query and fragment are rejected so tokens and other secret
    material cannot leak into a shareable reference.  Raw bodies, file paths
    and arbitrary strings are never considered: only explicit ``ref`` and
    ``reference`` fields are candidates.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.scheme not in _SAFE_SCHEMES:
        return None
    if parts.username or parts.password or parts.query or parts.fragment:
        return None
    if not parts.hostname:
        return None
    return value


def _references(*candidates):
    """Collect safe locators from explicit ``ref``/``reference`` fields only."""
    refs = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key in ("ref", "reference"):
            safe = _safe_ref(candidate.get(key))
            if safe is not None and safe not in refs:
                refs.append(safe)
    return refs


def _train_built(fact):
    """Return ``(state, checked_sha, train_id)`` for the latest train build."""
    built = [e for e in _events(fact) if e.get("type") == "train.built"]
    if not built:
        return "missing", None, None
    data = _event_data(built[-1])
    train_id = data.get("train_id")
    if data.get("passed") is False:
        return "rejected", None, train_id
    sha = data.get("checked_sha")
    if not sha:
        return "missing", None, train_id
    return "observed", sha, train_id


def _parse_ts(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _expired(expires_at, now):
    expires = _parse_ts(expires_at)
    if expires is None:
        return True  # an unparseable expiry cannot be trusted as fresh
    current = now
    if getattr(current, "tzinfo", None) is None:
        current = current.replace(tzinfo=timezone.utc)
    return expires <= current


def _gates(fact):
    details = {}
    if _group_state(fact) != "observed":
        return _entry("gates", "unknown", fact)
    gates = [e for e in _events(fact) if e.get("type") == "gate.result"]
    details["gates"] = [{"name": _event_data(e).get("gate"),
                         "passed": _event_data(e).get("passed")} for e in gates]
    if not gates:
        return _entry("gates", "missing", fact)
    if any(_event_data(e).get("passed") is False for e in gates):
        return _entry("gates", "rejected", fact, details=details)
    return _entry("gates", "observed", fact, details=details)


def _checked_commit(fact):
    if _group_state(fact) != "observed":
        return _entry("checked-commit", "unknown", fact)
    state, checked_sha, train_id = _train_built(fact)
    details = _pick({"train_id": train_id, "checked_sha": checked_sha}, ("train_id", "checked_sha"))
    return _entry("checked-commit", state, fact, details=details)


def _deploy(fact, checked_sha, train_id, now):
    if _group_state(fact) != "observed":
        return _entry("deploy", "unknown", fact)
    deployed = [e for e in _events(fact) if e.get("type") == "train.deployed"
                and (train_id is None or _event_data(e).get("train_id") == train_id)]
    if not deployed:
        return _entry("deploy", "missing", fact, details=_pick({"train_id": train_id}, ("train_id",)))
    data = _event_data(deployed[-1])
    details = _pick(data, ("train_id", "checked_sha", "expires_at"))
    if data.get("passed") is False:
        return _entry("deploy", "rejected", fact, details=details)
    expires_at = data.get("expires_at")
    if not expires_at:
        return _entry("deploy", "missing", fact, details=details)
    if _expired(expires_at, now):
        return _entry("deploy", "stale", fact, details=details)
    deploy_sha = data.get("checked_sha")
    if not deploy_sha or not checked_sha:
        return _entry("deploy", "missing", fact, details=details)
    if deploy_sha != checked_sha:
        return _entry("deploy", "stale", fact, details=details)
    return _entry("deploy", "observed", fact, details=details)


def _landing(fact, checked_sha, train_id):
    if _group_state(fact) != "observed":
        return _entry("landing", "unknown", fact)
    landed = [e for e in _events(fact) if e.get("type") == "item.landed"]
    if not landed:
        return _entry("landing", "missing", fact)
    data = _event_data(landed[-1])
    details = _pick(data, ("train_id", "landed_sha"))
    if train_id is not None and data.get("train_id") not in (None, train_id):
        return _entry("landing", "stale", fact, details=details)
    landed_sha = data.get("landed_sha")
    if not landed_sha or not checked_sha:
        return _entry("landing", "missing", fact, details=details)
    if landed_sha != checked_sha:
        return _entry("landing", "stale", fact, details=details)
    return _entry("landing", "observed", fact, details=details)


def _evidence_chain(fact):
    if _group_state(fact) != "observed":
        return _entry("evidence-chain", "unknown", fact)
    value = fact.get("value")
    item = value.get("item") if isinstance(value, dict) else None
    if not isinstance(item, dict):
        return _entry("evidence-chain", "missing", fact)
    refs = _references(item)
    details = _pick(item, ("chain_seq",))
    if item.get("chain_seq") is None:
        return _entry("evidence-chain", "missing", fact, refs, details)
    return _entry("evidence-chain", "observed", fact, refs, details)


def _outcome_report(fact):
    if _group_state(fact) != "observed":
        return _entry("outcome-report", "unknown", fact)
    synced = [e for e in _events(fact) if e.get("type") == "work.synced"]
    if not synced:
        return _entry("outcome-report", "missing", fact)
    data = _event_data(synced[-1])
    details = _pick(data, ("work", "train_id", "closed", "ok", "owner_reported", "pending_owner"))
    if data.get("ok") is False:
        return _entry("outcome-report", "rejected", fact, details=details)
    return _entry("outcome-report", "observed", fact, details=details)


def _owner_decision(fact, expected_work_id):
    """Only ``done`` + ``accepted`` from an authoritative owner is acceptance."""
    if _group_state(fact) != "observed":
        return _entry("owner-decision", "unknown", fact)
    value = fact.get("value")
    if not isinstance(value, dict):
        return _entry("owner-decision", "unknown", fact)
    item = value.get("item")
    if isinstance(item, dict):
        work_id, status, resolution = item.get("work_id"), item.get("status"), item.get("resolution")
        authoritative = (value.get("authority") == "sprintctl" and value.get("state") == "ok"
                         and _parse_ts(value.get("as_of")) is not None)
        matched = (isinstance(work_id, int) and not isinstance(work_id, bool)
                   and expected_work_id is not None and work_id == expected_work_id)
        if not authoritative or not matched or status not in (
                "pending", "active", "blocked", "done",
                "pending-verification", "awaiting-verification") \
                or "resolution" not in item:
            return _entry("owner-decision", "unknown", fact)
    else:
        # Flat synthetic fixtures remain readable, but never become authority.
        status, resolution = value.get("state"), value.get("resolution")
    details = _pick({"work_id": item.get("work_id") if isinstance(item, dict) else None,
                     "status": status, "resolution": resolution},
                    ("work_id", "status", "resolution"))
    if isinstance(item, dict) and status == "done" and resolution == "accepted":
        return _entry("owner-decision", "observed", fact, details=details)
    if status == "done" or resolution in ("completed", "rejected", "withdrawn"):
        return _entry("owner-decision", "rejected", fact, details=details)
    return _entry("owner-decision", "missing", fact, details=details)


def _outcome(entries):
    """The outcome label is owner acceptance; local gaps stay entry states."""
    states = {entry["kind"]: entry["state"] for entry in entries}
    owner = states["owner-decision"]
    if owner == "observed":
        return "accepted"
    if owner == "rejected":
        return "rejected"
    if owner == "unknown":
        return "unknown"
    return "pending"


def evidence_bundle(row, now=None):
    """Project one lifecycle row into a read-only evidence bundle.

    ``row`` is a lifecycle snapshot with ``item_id``, ``attempt_id`` and
    ``facts``.  ``now`` is the freshness reference for deploy expiry; when
    omitted the current UTC time is used.  The input is never mutated.
    """
    if not isinstance(row, dict):
        raise ValueError("evidence_bundle expects a lifecycle row dict")
    current = now if now is not None else datetime.now(timezone.utc)
    train = _fact(row, "local.train")
    _, checked_sha, train_id = _train_built(train)
    entries = [
        _gates(_fact(row, "local.attempt")),
        _checked_commit(train),
        _deploy(train, checked_sha, train_id, current),
        _landing(_fact(row, "local.receipt"), checked_sha, train_id),
        _evidence_chain(_fact(row, "work.evidence.tail-v1")),
        _outcome_report(_fact(row, "local.receipt")),
        _owner_decision(_fact(row, "work.public.item-v1"), row.get("work_id")),
    ]
    return {"item_id": row.get("item_id"), "work_id": row.get("work_id"),
            "attempt_id": row.get("attempt_id"), "outcome": _outcome(entries),
            "entries": entries}


def render_bundle(bundle):
    """Render a bundle as plain text: the verdict plus one line per entry."""
    lines = [f"item={bundle.get('item_id')} work={bundle.get('work_id')} "
             f"attempt={bundle.get('attempt_id')} outcome={bundle.get('outcome')}"]
    for entry in bundle.get("entries", ()):
        refs = ",".join(entry.get("references", ())) or "-"
        details = " ".join(f"{name}={value}" for name, value in sorted(entry.get("details", {}).items()))
        lines.append(f"{entry['kind']} state={entry['state']} "
                     f"source={entry['source']} revision={entry['revision']} "
                     f"checkpoint={entry['checkpoint']} "
                     f"observed_at={entry['observed_at']} references={refs}"
                     + (f" details={details}" if details else ""))
    return "\n".join(lines)


def register(sub):
    parser = sub.add_parser("verify", help="read-only lifecycle evidence bundles and verification review")
    parser.add_argument("--repo", required=True, help="configured owner repository")
    parser.add_argument("--item", required=True, help="local work/release identifier")
    parser.add_argument("--json", action="store_true", help="emit the bundles as JSON")
    return {"verify": _cmd}


def _cmd(args, log, *, client=None):
    """CLI adapter kept thin so tests can provide a fake catalog client."""
    if client is None:
        from .coordination import configured
        coordinator = configured(args.repo)
        if coordinator is None:
            print(f"{args.repo}: Vuoro coordination is not configured")
            return 1
        client = coordinator.client
        journal_path = coordinator.path
    else:
        journal_path = None
    from .config import load_releases
    from .lifecycle import release_work_ids
    work_ids = release_work_ids(load_releases())
    rows = lifecycle_rows(client, log.read(), item_id=args.item, work_ids=work_ids,
                          journal_path=journal_path)
    bundles = [evidence_bundle(row) for row in rows]
    if args.json:
        print(json.dumps({"bundles": bundles}, sort_keys=True))
    else:
        for bundle in bundles:
            print(render_bundle(bundle))
    return 0
