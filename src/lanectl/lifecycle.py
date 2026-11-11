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


def lifecycle(client, *, item_id=None, run_id=None, attempt_id=None, journal_path=None):
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
        return {"item_id": item_id, "run_id": run_id, "attempt_id": attempt_id,
                "facts": {name: dict(unknown, source=name) for name in READS}}
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
    return {"item_id": item_id, "run_id": run_id, "attempt_id": attempt_id, "facts": facts}


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


def attention_reasons(snapshot):
    """Pure reason codes over a lifecycle snapshot; no local verdict is stored."""
    facts = snapshot.get("facts", {})
    reasons = []
    for name, fact in facts.items():
        if fact.get("state") == "unknown":
            reasons.append({"code": "owner-unknown", "fact": name,
                            "next_action": "refresh owner read"})
    lease = facts.get("work.lease.read-v1", {})
    if lease.get("state") == "unknown" and "runner-operation-denied" in lease.get("reason", ""):
        reasons.append({"code": "lease-unknown", "fact": "work.lease.read-v1",
                        "next_action": "wait for an authorized lease read"})
    item = facts.get("work.public.item-v1", {})
    if item.get("state") == "observed":
        value = item.get("value", {})
        # The item result itself stays opaque; only catalog-independent terms are classified.
        if value.get("state") in ("pending-verification", "awaiting-verification"):
            reasons.append({"code": "pending-verification", "fact": "work.public.item-v1",
                            "next_action": "refresh owner decision"})
    return reasons
