"""Compatibility with captured public owner catalog schemas and fail-closed behavior."""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from lanectl.lifecycle import _valid, lifecycle, ready_work

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
def test_unsupported_regex_forms_fail_closed(pattern, value):
    assert not _valid(value, {"type": "string", "pattern": pattern})


@pytest.mark.parametrize("suffix", ["\r", "\n", "\u2028", "\u2029"])
def test_pattern_end_anchor_rejects_final_line_terminators(suffix):
    assert not _valid("x" + suffix, {"type": "string", "pattern": "^x$"})
    schema = SCHEMAS["work.run.resolve-v1"]["input_schema"]["properties"]["run_id"]
    assert not _valid(RUN + suffix, schema)
    assert not _valid("prefix" + RUN, schema)


def test_evidence_with_claims_freshness_and_validity():
    item = {"item_id": "e1", "kind": "test", "ref": "ref", "digest": "digest", "collector": "collector",
            "validity": {"basis": "bounded", "valid_from": "now", "valid_until": "later", "component_digests": {}},
            "claims": [{"claim_type": "observation", "subject": "subject", "grant_id": None,
                        "freshness": {"scope": "repo", "position": 0}, "confirms": True, "detail": {}}],
            "provenance": {}, "chain_seq": 0, "chain_prev_digest": None}
    result = dict(RESULTS["work.evidence.tail-v1"], item=item)
    schema = SCHEMAS["work.evidence.tail-v1"]["result_schema"]
    assert _valid(result, schema)
    for path, bad in [(('item', 'validity', 'basis'), 'unknown'),
                      (('item', 'claims', 0, 'freshness', 'scope'), ''),
                      (('item', 'claims', 0, 'confirms'), 1),
                      (('item', 'chain_seq'), -1)]:
        corrupted = deepcopy(result)
        target = corrupted
        for key in path[:-1]: target = target[key]
        target[path[-1]] = bad
        assert not _valid(corrupted, schema)


def test_nonempty_lease_history_reports_checks_and_parked():
    lease_id = "lease_" + "0" * 26
    other_id = "lease_" + "1" * 26
    lease = {"lease_id": lease_id, "generation": 1, "item_id": 1, "run_id": RUN,
             "principal_id": "p", "workspace_id": "w", "state": "active", "ttl_seconds": 30,
             "heartbeat_interval_seconds": 1, "acquired_at": "now", "heartbeat_at": "now",
             "expires_at": "later", "ended_at": None, "end_reason": None, "takeover_of": other_id,
             "superseded_by": other_id, "verification": VERIFICATION, "stale": False}
    report = {"report_id": "outcome_" + "0" * 26, "item_id": 1, "lease_id": lease_id,
              "run_id": RUN, "principal_id": "p", "outcome": "succeeded", "summary": "done",
              "payload": {}, "checks": [{"name": "unit", "status": "passed", "ref": "ref"}],
              "payload_digest": "a" * 64, "disposition": "recorded", "reason_code": None,
              "verification_profile": "checked", "decision_id": None, "created_at": "now",
              "parked": {"event_id": 1, "reason_ref": "reason"}}
    parked = {"event_id": 1, "reason_ref": "reason", "report_id": report["report_id"],
              "lease_id": lease_id, "parked_at": "now"}
    result = dict(RESULTS["work.lease.read-v1"], current_lease=lease, leases=[{k: v for k, v in lease.items() if k != "stale"}],
                  outcome_reports=[report], parked=parked)
    schema = SCHEMAS["work.lease.read-v1"]["result_schema"]
    assert _valid(result, schema)
    for path, bad in [(('leases', 0, 'takeover_of'), 'invalid'),
                      (('current_lease', 'superseded_by'), 'invalid'),
                      (('outcome_reports', 0, 'checks', 0, 'status'), 'unknown'),
                      (('outcome_reports', 0, 'parked', 'event_id'), 0),
                      (('parked', 'event_id'), True)]:
        corrupted = deepcopy(result)
        target = corrupted
        for key in path[:-1]: target = target[key]
        target[path[-1]] = bad
        assert not _valid(corrupted, schema)


def test_public_item_blocked_by_nonempty_and_invalid_values():
    result = deepcopy(RESULTS["work.public.item-v1"])
    result["item"]["blocked_by"] = [1, 2]
    schema = SCHEMAS["work.public.item-v1"]["result_schema"]
    assert _valid(result, schema)
    result["item"]["blocked_by"] = [1, True]
    assert not _valid(result, schema)


@pytest.mark.parametrize("input_schema,work_id", [
    ({"type": "object", "properties": {"work_id": {"type": "integer", "format": "unknown"}}}, 1),
    (SCHEMAS["work.public.item-v1"]["input_schema"], 0),
])
def test_lifecycle_rejects_unsupported_or_mismatched_input_before_invoke(input_schema, work_id):
    class Client:
        def discover(self):
            return {"revision": "r", "operations": [{"name": "work.public.item-v1", "execution_semantics": "read",
                    "repo_scoped": True, "input_schema": input_schema,
                    "result_schema": SCHEMAS["work.public.item-v1"]["result_schema"]}]}
        def invoke(self, envelope):
            raise AssertionError("invalid input must not reach owner")
        def envelope(self, *args):
            raise AssertionError("invalid input must not reach owner")
    fact = lifecycle(Client(), item_id="local", work_id=work_id)["facts"]["work.public.item-v1"]
    assert fact["state"] == "unknown" and "value" not in fact


def test_overdeep_data_fails_closed():
    value = "leaf"
    for _ in range(150): value = [value]
    assert not _valid(value, {})
