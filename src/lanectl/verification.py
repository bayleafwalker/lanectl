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


def _entry(kind, state, fact, references=()):
    return {"kind": kind, "state": state, **_provenance(fact),
            "references": list(references)}


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
    """Return ``(state, checked_sha)`` for the latest train build record."""
    built = [e for e in _events(fact) if e.get("type") == "train.built"]
    if not built:
        return "missing", None
    data = _event_data(built[-1])
    if data.get("passed") is False:
        return "rejected", None
    sha = data.get("checked_sha")
    if not sha:
        return "missing", None
    return "observed", sha


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
    if _group_state(fact) != "observed":
        return _entry("gates", "unknown", fact)
    gates = [e for e in _events(fact) if e.get("type") == "gate.result"]
    if not gates:
        return _entry("gates", "missing", fact)
    if any(_event_data(e).get("passed") is False for e in gates):
        return _entry("gates", "rejected", fact)
    return _entry("gates", "observed", fact)


def _checked_commit(fact):
    if _group_state(fact) != "observed":
        return _entry("checked-commit", "unknown", fact)
    state, _ = _train_built(fact)
    return _entry("checked-commit", state, fact)


def _deploy(fact, checked_sha, now):
    if _group_state(fact) != "observed":
        return _entry("deploy", "unknown", fact)
    deployed = [e for e in _events(fact) if e.get("type") == "train.deployed"]
    if not deployed:
        return _entry("deploy", "missing", fact)
    data = _event_data(deployed[-1])
    if data.get("passed") is False:
        return _entry("deploy", "rejected", fact)
    expires_at = data.get("expires_at")
    if not expires_at:
        return _entry("deploy", "missing", fact)
    if _expired(expires_at, now):
        return _entry("deploy", "stale", fact)
    deploy_sha = data.get("checked_sha")
    if not deploy_sha or not checked_sha:
        return _entry("deploy", "missing", fact)
    if deploy_sha != checked_sha:
        return _entry("deploy", "stale", fact)
    return _entry("deploy", "observed", fact)


def _landing(fact, checked_sha):
    if _group_state(fact) != "observed":
        return _entry("landing", "unknown", fact)
    landed = [e for e in _events(fact) if e.get("type") == "item.landed"]
    if not landed:
        return _entry("landing", "missing", fact)
    data = _event_data(landed[-1])
    landed_sha = data.get("landed_sha")
    if not landed_sha or not checked_sha:
        return _entry("landing", "missing", fact)
    if landed_sha != checked_sha:
        return _entry("landing", "stale", fact)
    return _entry("landing", "observed", fact)


def _evidence_chain(fact):
    if _group_state(fact) != "observed":
        return _entry("evidence-chain", "unknown", fact)
    value = fact.get("value")
    item = value.get("item") if isinstance(value, dict) else None
    if not isinstance(item, dict):
        return _entry("evidence-chain", "missing", fact)
    refs = _references(item)
    if item.get("chain_seq") is None:
        return _entry("evidence-chain", "missing", fact, refs)
    return _entry("evidence-chain", "observed", fact, refs)


def _outcome_report(fact):
    if _group_state(fact) != "observed":
        return _entry("outcome-report", "unknown", fact)
    synced = [e for e in _events(fact) if e.get("type") == "work.synced"]
    if not synced:
        return _entry("outcome-report", "missing", fact)
    data = _event_data(synced[-1])
    if data.get("ok") is False:
        return _entry("outcome-report", "rejected", fact)
    return _entry("outcome-report", "observed", fact)


def _owner_decision(fact):
    if _group_state(fact) != "observed":
        return _entry("owner-decision", "unknown", fact)
    value = fact.get("value")
    item = value.get("item") if isinstance(value, dict) else None
    if not isinstance(item, dict):
        return _entry("owner-decision", "unknown", fact)
    status, resolution = item.get("status"), item.get("resolution")
    if status == "done" and resolution == "completed":
        return _entry("owner-decision", "observed", fact)
    if status == "done" and resolution is not None:
        return _entry("owner-decision", "rejected", fact)
    # awaiting-verification and every other not-yet-decided status are pending.
    return _entry("owner-decision", "missing", fact)


def _outcome(entries):
    states = {entry["kind"]: entry["state"] for entry in entries}
    if "rejected" in states.values():
        return "rejected"
    if "stale" in states.values():
        return "stale"
    if states["owner-decision"] == "unknown":
        return "unknown"
    if states["owner-decision"] != "observed":
        return "pending"
    if "unknown" in states.values():
        return "unknown"
    if "missing" in states.values():
        return "missing"
    return "accepted"


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
    _, checked_sha = _train_built(train)
    entries = [
        _gates(_fact(row, "local.attempt")),
        _checked_commit(train),
        _deploy(train, checked_sha, current),
        _landing(_fact(row, "local.receipt"), checked_sha),
        _evidence_chain(_fact(row, "work.evidence.tail-v1")),
        _outcome_report(_fact(row, "local.receipt")),
        _owner_decision(_fact(row, "work.public.item-v1")),
    ]
    return {"item_id": row.get("item_id"), "attempt_id": row.get("attempt_id"),
            "outcome": _outcome(entries), "entries": entries}


def render_bundle(bundle):
    """Render a bundle as plain text: the verdict plus one line per entry."""
    lines = [f"item={bundle.get('item_id')} attempt={bundle.get('attempt_id')} "
             f"outcome={bundle.get('outcome')}"]
    for entry in bundle.get("entries", ()):
        refs = ",".join(entry.get("references", ())) or "-"
        lines.append(f"{entry['kind']} state={entry['state']} "
                     f"source={entry['source']} revision={entry['revision']} "
                     f"checkpoint={entry['checkpoint']} "
                     f"observed_at={entry['observed_at']} references={refs}")
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
    rows = lifecycle_rows(client, log.read(), item_id=args.item, journal_path=journal_path)
    bundles = [evidence_bundle(row) for row in rows]
    if args.json:
        print(json.dumps({"bundles": bundles}, sort_keys=True))
    else:
        for bundle in bundles:
            print(render_bundle(bundle))
    return 0
