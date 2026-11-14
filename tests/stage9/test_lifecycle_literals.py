"""Catalog literal constraints must preserve owner fact provenance."""
import pytest

from lanectl.lifecycle import _valid, ready_work


class ListClient:
    def __init__(self, result):
        self.result = result

    def discover(self):
        return {"revision": "owner-revision", "operations": [{
            "name": "work.public.list-v1", "repo_scoped": True,
            "execution_semantics": "read", "input_schema": {"type": "object"},
            "result_schema": {"type": "object", "required": ["authority", "as_of", "state", "items"],
                              "properties": {"authority": {"const": "sprintctl"},
                                             "state": {"enum": ["ok", "unavailable"]},
                                             "as_of": {"type": "string"},
                                             "items": {"type": "array", "items": {"type": "object"}}}},
        }]}

    def envelope(self, operation, arguments, key):
        return operation, arguments

    def invoke(self, envelope):
        return self.result


def test_catalog_literals_allow_observed_owner_list():
    result = {"authority": "sprintctl", "state": "ok", "as_of": "2026-11-14T00:00:00Z", "items": []}
    fact = ready_work(ListClient(result))
    assert fact["state"] == "observed"
    assert fact["value"] == result
    assert fact["revision"] == "owner-revision"


@pytest.mark.parametrize("changes", [
    {"authority": "other"}, {"state": "other"}, {"as_of": 42},
    {"state": "unavailable"}, {"items": "not an array"},
])
def test_invalid_or_unavailable_owner_list_stays_unknown(changes):
    result = {"authority": "sprintctl", "state": "ok", "as_of": "2026-11-14T00:00:00Z", "items": []}
    result.update(changes)
    assert ready_work(ListClient(result))["state"] == "unknown"


@pytest.mark.parametrize("value,schema,expected", [
    ("ok", {"const": "ok", "enum": ["ok", "other"], "type": "string"}, True),
    ("ok", {"const": "ok", "enum": ["other"]}, False),
    ("1", {"const": "1", "type": "integer"}, False),
    (True, {"const": 1}, False), (1, {"enum": [True]}, False),
    (1.0, {"const": 1}, True),
    ({"x": [1, False]}, {"const": {"x": [1.0, False]}}, True),
    ({"x": [1, False]}, {"const": {"x": [True, False]}}, False),
    ("ok", {"enum": "ok"}, False), ("ok", {"enum": []}, False),
    ("ok", {"const": "ok", "pattern": "^ok$"}, False),
    ("ok", {"const": "ok", "type": "unsupported"}, False),
    ("ok", {"const": float("nan")}, False),
    ({}, {"type": "object", "properties": {"absent": {"const": "x", "pattern": "x"}}}, False),
    ([], {"type": "array", "items": {"enum": []}}, False),
])
def test_literal_constraints(value, schema, expected):
    assert _valid(value, schema) is expected
