"""Read-only, catalog-checked lifecycle snapshots for operator surfaces.

The owner is authoritative for work, run, lease and evidence facts.  The local
coordination journal is deliberately used only to recover the identifiers with
which to ask the owner; it never fills an unavailable owner fact.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from .coordination import CoordinationError


READS = ("work.public.item-v1", "work.run.resolve-v1", "work.lease.read-v1",
         "work.evidence.tail-v1")
LIST = "work.public.list-v1"


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


LOCAL_FACTS = ("local.release", "local.attempt", "local.train", "local.receipt")


def _event_fact(name, events):
    """Make a read-only, auditable fact from local append-only events.

    ``checkpoint`` is the one-based log position.  It deliberately accompanies
    (rather than replaces) ``revision``: local events do not all have a domain
    revision, while a checkpoint tells an operator exactly what was read.
    """
    if not events:
        return {"state": "unknown", "source": "lanectl.events", "revision": None,
                "checkpoint": None, "observed_at": _now(), "reason": "no matching local record"}
    indexed = list(events)
    latest = indexed[-1]
    revision = latest[1]["data"].get("revision")
    return {"state": "observed", "source": "lanectl.events", "revision": revision,
            "checkpoint": latest[0], "observed_at": latest[1]["ts"],
            "value": [event for _, event in indexed]}


def local_facts(events, *, item_id=None, attempt_id=None, run_id=None):
    """Project local release, attempt, train and receipt records into facts.

    This is intentionally a projection, not a second state machine.  Values
    retain the validated event payloads, so mismatched identifiers remain
    inspectable instead of being silently joined to owner values.
    """
    numbered = list(enumerate(events or (), 1))
    releases = [(n, e) for n, e in numbered if e.get("type") == "release.published"
                and (item_id is None or e.get("item_id") == item_id or e.get("data", {}).get("release_id") == item_id)]
    attempts = [(n, e) for n, e in numbered if e.get("data", {}).get("attempt_id") == attempt_id]
    # With no supplied attempt, select records for the requested item.  A row
    # builder supplies an attempt id, preventing unrelated attempts from joining.
    if attempt_id is None and item_id is not None:
        attempts = [(n, e) for n, e in numbered if e.get("item_id") == item_id
                    and e.get("type") in ("item.claimed", "attempt.finished", "gate.result", "decision.recorded")]
    attempt_ids = {e.get("data", {}).get("attempt_id") for _, e in attempts}
    trains = [(n, e) for n, e in numbered if e.get("type") in ("train.built", "train.deployed", "train.torn_down")
              and (attempt_id is None or attempt_id in e.get("data", {}).get("attempts", [])
                   or e.get("data", {}).get("attempt_id") == attempt_id)]
    train_ids = {e.get("data", {}).get("train_id") for _, e in trains}
    receipts = [(n, e) for n, e in numbered if e.get("type") in ("item.landed", "work.synced")
                and (attempt_id is None or e.get("data", {}).get("attempt_id") == attempt_id
                     or e.get("data", {}).get("train_id") in train_ids)
                and (item_id is None or e.get("item_id") == item_id or e.get("data", {}).get("attempt_id") in attempt_ids)]
    return {"local.release": _event_fact("local.release", releases),
            "local.attempt": _event_fact("local.attempt", attempts),
            "local.train": _event_fact("local.train", trains),
            "local.receipt": _event_fact("local.receipt", receipts)}


def _valid(value, schema):
    """Small, conservative JSON-schema validator for catalog result schemas."""
    if not isinstance(schema, dict):
        return False
    kind = schema.get("type")
    if kind == "object":
        if not isinstance(value, dict):
            return False
        if any(name not in value for name in schema.get("required", ())):
            return False
        return all(name not in schema.get("properties", {}) or _valid(item, schema["properties"][name])
                   for name, item in value.items())
    if kind == "array":
        return isinstance(value, list) and all(_valid(item, schema.get("items", {})) for item in value)
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "null":
        return value is None
    return False


def _definition(catalog, operation):
    definition = next((item for item in catalog["operations"] if item.get("name") == operation), None)
    if not isinstance(definition, dict):
        raise CoordinationError(f"owner operation unavailable: {operation}")
    if definition.get("execution_semantics") != "read" or not definition.get("repo_scoped"):
        raise CoordinationError(f"owner operation is not a repository-scoped read: {operation}")
    if not isinstance(definition.get("result_schema"), dict):
        raise CoordinationError(f"owner operation lacks a result schema: {operation}")
    return definition


def _arguments(definition, values):
    schema = definition.get("input_schema", {})
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    required = schema.get("required", ()) if isinstance(schema, dict) else ()
    result = {name: values[name] for name in properties if name in values}
    if any(name not in result for name in required):
        raise CoordinationError("owner catalog cannot construct required read arguments")
    if any(not _valid(value, properties[name]) for name, value in result.items()):
        raise CoordinationError("owner catalog arguments do not match input schema")
    return result


def journal_binding(journal_path, attempt_id):
    """Return a persisted identifier hint, never a fact about the owner."""
    if not journal_path or not attempt_id:
        return None
    try:
        with sqlite3.connect(Path(journal_path)) as db:
            row = db.execute("SELECT binding FROM bindings WHERE attempt=?", (attempt_id,)).fetchone()
        return None if row is None else json.loads(row[0])
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return None


def _fact(client, catalog, operation, values):
    observed_at = _now()
    try:
        definition = _definition(catalog, operation)
        result = client.invoke(client.envelope(operation, _arguments(definition, values), None))
        if not _valid(result, definition["result_schema"]):
            raise CoordinationError("owner result does not match catalog result schema")
        return {"state": "observed", "source": operation, "revision": catalog["revision"],
                "observed_at": observed_at, "value": result}
    except CoordinationError as exc:
        return {"state": "unknown", "source": operation, "revision": catalog.get("revision"),
                "observed_at": observed_at, "reason": str(exc)}


def lifecycle(client, *, item_id=None, run_id=None, attempt_id=None, journal_path=None, events=None):
    """Join fresh owner reads into one snapshot without manufacturing state.

    ``attempt_id`` and ``journal_path`` may recover identifiers after restart,
    but all returned owner values come from fresh catalog-advertised reads.
    """
    hint = journal_binding(journal_path, attempt_id)
    if hint:
        item_id = item_id if item_id is not None else hint.get("item_id")
        run_id = run_id if run_id is not None else hint.get("run_id")
    try:
        catalog = client.discover()
        if not isinstance(catalog.get("revision"), str):
            raise CoordinationError("invalid owner catalog")
    except CoordinationError as exc:
        unknown = {"state": "unknown", "source": "owner", "revision": None,
                   "observed_at": _now(), "reason": str(exc)}
        facts = {name: dict(unknown, source=name) for name in READS}
        if events is not None:
            facts.update(local_facts(events, item_id=item_id, attempt_id=attempt_id, run_id=run_id))
        return {"item_id": item_id, "run_id": run_id, "attempt_id": attempt_id, "facts": facts}
    values = {"item_id": item_id, "work_id": item_id, "run_id": run_id}
    facts = {}
    for operation in READS:
        if operation in ("work.public.item-v1", "work.lease.read-v1") and item_id is None:
            facts[operation] = {"state": "unknown", "source": operation,
                                "revision": catalog["revision"], "observed_at": _now(),
                                "reason": "no item identifier available"}
        elif operation in ("work.run.resolve-v1", "work.evidence.tail-v1") and run_id is None:
            facts[operation] = {"state": "unknown", "source": operation,
                                "revision": catalog["revision"], "observed_at": _now(),
                                "reason": "no run identifier available"}
        else:
            facts[operation] = _fact(client, catalog, operation, values)
    if events is not None:
        facts.update(local_facts(events, item_id=item_id, attempt_id=attempt_id, run_id=run_id))
    return {"item_id": item_id, "run_id": run_id, "attempt_id": attempt_id, "facts": facts}


def lifecycle_rows(client, events, *, item_id=None, run_id=None, journal_path=None):
    """Return one normalized lifecycle row for every local attempt.

    The item id comes from the local claim event and is passed unchanged to the
    owner.  Thus an owner/local ID mismatch is visible in the two facts instead
    of being coerced into a false join.
    """
    claims = [event for event in events if event.get("type") == "item.claimed"
              and (item_id is None or event.get("item_id") == item_id)]
    if not claims and item_id is not None:
        return [lifecycle(client, item_id=item_id, run_id=run_id, events=events,
                          journal_path=journal_path)]
    rows = []
    for claim in claims:
        data = claim["data"]
        rows.append(lifecycle(client, item_id=claim.get("item_id"), run_id=run_id,
                              attempt_id=data.get("attempt_id"), events=events,
                              journal_path=journal_path))
    return rows


def ready_work(client):
    """Return the owner's ordered public list as one sourced read fact.

    No sorting or filtering is applied: owner order remains visible to the UI.
    """
    observed_at = _now()
    try:
        catalog = client.discover()
        if not isinstance(catalog.get("revision"), str):
            raise CoordinationError("invalid owner catalog")
        return _fact(client, catalog, LIST, {})
    except CoordinationError as exc:
        return {"state": "unknown", "source": LIST, "revision": None,
                "observed_at": observed_at, "reason": str(exc)}


REASON_RULES = {
    # Rules are deliberately adjacent to the exported codes: these are UI hints,
    # never authority to mutate a work item.
    "lease-uncertainty": "The owner lease fact is unknown or not active.",
    "revalidation": "A passed train has no checked tip, or its checked tip differs from an attempt head.",
    "gate-failure": "A local gate, train check, or deploy health record reports passed=false.",
    "stale-deploy": "A successful deploy has expired, or a local fact exceeds the requested freshness threshold.",
    "pending-verification": "The owner item explicitly awaits verification.",
    "reconcile": "A landing/receipt is incomplete: tracker sync failed or an attempt lacks an outcome.",
    "owner-unknown": "A catalog-advertised owner read could not establish a fact.",
}


def _reason(code, evidence, actions):
    return {"code": code, "rule": REASON_RULES[code], "evidence": evidence,
            "next_actions": actions, "fact": evidence[0]["fact"], "next_action": actions[0]}


def _values(fact):
    value = fact.get("value", [])
    return value if isinstance(value, list) else []


def attention_reasons(snapshot, *, now=None, stale_after_s=None):
    """Pure, table-testable classifier; it performs no reads or writes."""
    facts = snapshot.get("facts", {})
    reasons = []
    for name, fact in facts.items():
        if fact.get("state") == "unknown":
            if name in READS:
                identifiers = {key: snapshot[key] for key in ("item_id", "run_id", "attempt_id")
                               if snapshot.get(key) is not None}
                reasons.append(_reason("owner-unknown", [{"fact": name, "identifiers": identifiers}],
                                       ["lanectl lifecycle --repo R --item N"]))
    lease = facts.get("work.lease.read-v1", {})
    if lease.get("state") == "unknown" or (lease.get("state") == "observed" and
                                              lease.get("value", {}).get("lease") not in ("active", "held", None)):
        reasons.append(_reason("lease-uncertainty", [{"fact": "work.lease.read-v1", "identifiers": {
            "item_id": snapshot.get("item_id")}}],
                               ["lanectl lifecycle --repo R --item N", "owner work lease read"] ))
        # Kept for callers of the initial UI-01 surface; new consumers should
        # use the precise, documented ``lease-uncertainty`` code above.
        if "runner-operation-denied" in lease.get("reason", ""):
            reasons.append({"code": "lease-unknown", "fact": "work.lease.read-v1",
                            "next_action": "wait for an authorized lease read"})
    item = facts.get("work.public.item-v1", {})
    if item.get("state") == "observed":
        value = item.get("value", {})
        # The item result itself stays opaque; only catalog-independent terms are classified.
        if value.get("state") in ("pending-verification", "awaiting-verification"):
            reasons.append(_reason("pending-verification", [{"fact": "work.public.item-v1", "identifiers": {
                "item_id": snapshot.get("item_id")}}],
                                   ["lanectl lifecycle --repo R --item N", "owner work item read"]))
    attempt, train, receipt = (_values(facts.get(name, {})) for name in ("local.attempt", "local.train", "local.receipt"))
    gates = [e for e in attempt if e.get("type") == "gate.result" and not e.get("data", {}).get("passed")]
    failed_train = [e for e in train if e.get("type") in ("train.built", "train.deployed") and not e.get("data", {}).get("passed")]
    if gates or failed_train:
        event = (gates + failed_train)[0]
        reasons.append(_reason("gate-failure", [{"fact": "local.attempt" if gates else "local.train", "identifiers": event.get("data", {})}],
                               ["lanectl events --item N", "lanectl train R"]))
    built = next((e for e in reversed(train) if e.get("type") == "train.built" and e.get("data", {}).get("passed")), None)
    finished = next((e for e in reversed(attempt) if e.get("type") == "attempt.finished"), None)
    if built and (not built["data"].get("checked_sha") or (finished and built["data"].get("checked_sha") != finished["data"].get("head_sha"))):
        reasons.append(_reason("revalidation", [{"fact": "local.train", "identifiers": built["data"]}],
                               ["lanectl recheck TRAIN_ID", "lanectl deploy run TRAIN_ID"]))
    if (receipt and (not finished or any(not e.get("data", {}).get("ok", True) for e in receipt if e.get("type") == "work.synced"))):
        reasons.append(_reason("reconcile", [{"fact": "local.receipt", "identifiers": receipt[-1].get("data", {})}],
                               ["lanectl work reconcile", "lanectl lifecycle --repo R --item N"]))
    if stale_after_s is not None:
        current = now or datetime.now(timezone.utc)
        for name, fact in facts.items():
            stamp = fact.get("observed_at")
            try:
                age = (current - datetime.fromisoformat(stamp.replace("Z", "+00:00"))).total_seconds()
            except (AttributeError, ValueError):
                continue
            if age > stale_after_s:
                reasons.append(_reason("stale-deploy", [{"fact": name, "identifiers": {
                    "item_id": snapshot.get("item_id"), "observed_at": stamp}}],
                                       ["lanectl deploy list", "lanectl lifecycle --repo R --item N"]))
                break
    return reasons


def render_rows(rows):
    """Small dependency-free table for terminals and tests."""
    lines = ["ITEM  ATTEMPT  OWNER  LOCAL  REASONS"]
    for row in rows:
        facts = row["facts"]
        unknown_owner = [name.rsplit(".", 1)[0] for name in READS
                         if facts.get(name, {}).get("state") == "unknown"]
        owner = ",".join(unknown_owner) if unknown_owner else "observed"
        if not unknown_owner and not any(facts.get(name, {}).get("state") == "observed" for name in READS):
            owner = "unknown"
        local = ",".join(name[6:] for name in LOCAL_FACTS
                         if facts.get(name, {}).get("state") == "observed") or "unknown"
        codes = ",".join(reason["code"] for reason in row.get("reasons", ())) or "-"
        lines.append(f"{row.get('item_id') or '-'}  {row.get('attempt_id') or '-'}  {owner}  {local}  {codes}")
    return "\n".join(lines)


def register(sub):
    parser = sub.add_parser("lifecycle", help="read-only joined owner and local lifecycle rows")
    parser.add_argument("--repo", required=True, help="configured owner repository")
    parser.add_argument("--item", help="local work/release identifier")
    parser.add_argument("--json", action="store_true", help="emit the same lifecycle snapshot as JSON")
    return {"lifecycle": _cmd}


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
    for row in rows:
        row["reasons"] = attention_reasons(row)
    if args.json:
        print(json.dumps({"rows": rows}, sort_keys=True))
    else:
        print(render_rows(rows))
    return 0
