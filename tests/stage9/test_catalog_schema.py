"""Compatibility with captured public owner catalog schemas and fail-closed behavior."""
import json
from pathlib import Path

import pytest

from lanectl.lifecycle import _valid, ready_work

SCHEMAS = json.loads(Path(__file__).with_name("catalog_schemas.json").read_text())
RUN = "run_" + "0" * 26
VERIFICATION = {"profile": "checked", "requirements": [], "required_checks": []}
RESULTS = {
    "work.public.list-v1": {"authority": "sprintctl", "state": "ok", "as_of": "now", "items": []},
    "work.public.item-v1": {"authority": "sprintctl", "state": "ok", "as_of": "now", "item": {
        "work_id": 1, "title": "Example", "priority": None, "status": "pending", "blocked": False,
        "updated_at": "now", "created_at": "now", "resolution": None, "blocked_by": []}},
    "work.run.resolve-v1": {"repo_id": "repo", "run_id": RUN, "principal_id": "p", "workspace_id": "w", "client_id": None, "grant_id": None},
    "work.lease.read-v1": {"repo_id": "repo", "item_id": 1, "current_lease": None, "leases": [], "outcome_reports": [], "verification": VERIFICATION, "evaluated_at": "now"},
    "work.evidence.tail-v1": {"repo_id": "repo", "run_id": RUN, "item": None},
}
INPUTS = {"work.public.list-v1": {}, "work.public.item-v1": {"work_id": 1},
          "work.run.resolve-v1": {"run_id": RUN}, "work.lease.read-v1": {"item_id": 1},
          "work.evidence.tail-v1": {"run_id": RUN}}


@pytest.mark.parametrize("operation", sorted(SCHEMAS))
def test_captured_catalog_accepts_valid_input_and_result(operation):
    assert _valid(INPUTS[operation], SCHEMAS[operation]["input_schema"])
    assert _valid(RESULTS[operation], SCHEMAS[operation]["result_schema"])


def test_ready_work_uses_captured_catalog_and_preserves_unavailable():
    class Client:
        def __init__(self, state): self.state = state
        def discover(self):
            return {"revision": "r", "operations": [{"name": "work.public.list-v1", "execution_semantics": "read", "repo_scoped": True, **SCHEMAS["work.public.list-v1"]}]}
        def envelope(self, operation, arguments, key): return arguments
        def invoke(self, envelope): return dict(RESULTS["work.public.list-v1"], state=self.state)
    assert ready_work(Client("ok"))["state"] == "observed"
    fact = ready_work(Client("unavailable"))
    assert fact["state"] == "unknown" and "value" not in fact


@pytest.mark.parametrize("value,schema,expected", [
    (None, {"type": ["integer", "null"], "minimum": 1}, True),
    (0, {"type": ["integer", "null"], "minimum": 1}, False),
    (True, {"type": ["integer", "null"]}, False),
    ("x", {"type": "string", "anyOf": [{"const": "x"}, {"const": "y"}], "minLength": 2}, False),
    ("abc", {"type": "string", "pattern": "b", "minLength": 3, "maxLength": 3}, True),
    ("abc", {"type": "string", "pattern": "^b"}, False),
    (3, {"type": "number", "minimum": 1, "maximum": 2}, False),
    ([1, 2], {"type": "array", "minItems": 1, "maxItems": 2}, True),
    ([1, 2, 3], {"type": "array", "maxItems": 2}, False),
    ({"extra": 1}, {"type": "object", "additionalProperties": False}, False),
    ({"extra": 1}, {"type": "object", "additionalProperties": True}, True),
    ("x", {"anyOf": [{"const": "x"}, {"const": "y", "format": "unknown"}]}, False),
    ("x", {"type": "string", "pattern": "["}, False),
    ("x", {"type": "string", "minLength": True}, False),
    ("x", {"$schema": "https://example.com/unknown", "type": "string"}, False),
])
def test_constraints_and_fail_closed(value, schema, expected):
    assert _valid(value, schema) is expected


def test_excessive_depth_fails_closed():
    schema = {"const": "x"}
    for _ in range(150): schema = {"anyOf": [schema]}
    assert not _valid("x", schema)


def test_captured_list_checks_nested_rows_and_closed_objects():
    schema = SCHEMAS["work.public.list-v1"]["result_schema"]
    row = {"work_id": 1, "title": "Example", "priority": 2, "status": "pending", "blocked": False, "updated_at": "now"}
    result = dict(RESULTS["work.public.list-v1"], items=[row])
    assert _valid(result, schema)
    for change in ({"work_id": True}, {"priority": 10}, {"title": ""},
                   {"status": "unknown"}, {"extra": "not allowed"}):
        assert not _valid(dict(result, items=[dict(row, **change)]), schema)


def test_captured_run_pattern_and_required_null_branch():
    schema = SCHEMAS["work.run.resolve-v1"]["result_schema"]
    result = RESULTS["work.run.resolve-v1"]
    assert not _valid(dict(result, run_id="run_bad"), schema)
    assert not _valid(dict(result, client_id=""), schema)
    assert _valid(dict(result, client_id="client"), schema)


def test_closed_schema_on_unused_branch_and_python_specific_pattern_rejected():
    assert not _valid("x", {"anyOf": [{"const": "x"}, {"type": "object", "additionalProperties": {}}]})
    assert not _valid("a", {"pattern": r"\w"})


def test_captured_lease_non_null_branch_checks_nested_constraints():
    lease = {"lease_id": "lease_" + "0" * 26, "generation": 1, "item_id": 1, "run_id": RUN,
             "principal_id": "p", "workspace_id": "w", "state": "active", "ttl_seconds": 30,
             "heartbeat_interval_seconds": 1, "acquired_at": "now", "heartbeat_at": "now",
             "expires_at": "later", "ended_at": None, "end_reason": None, "takeover_of": None,
             "superseded_by": None, "verification": VERIFICATION, "stale": False}
    result = dict(RESULTS["work.lease.read-v1"], current_lease=lease)
    schema = SCHEMAS["work.lease.read-v1"]["result_schema"]
    assert _valid(result, schema)
    for change in ({"ttl_seconds": 29}, {"lease_id": "wrong"}, {"stale": 1}, {"unknown": 1}):
        assert not _valid(dict(result, current_lease=dict(lease, **change)), schema)


@pytest.mark.parametrize("pattern,value", [
    ("^a.b$", "a\rb"),
    ("x{999999999999999999999999}", "x"),
])
def test_divergent_or_oversized_patterns_fail_closed(pattern, value):
    assert not _valid(value, {"type": "string", "pattern": pattern})
