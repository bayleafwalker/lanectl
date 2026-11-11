"""Lifecycle reads use catalog schemas and retain owner uncertainty."""
from lanectl.coordination import CoordinationError
from lanectl.lifecycle import attention_reasons, lifecycle, ready_work


def schema(properties, required):
    return {"type": "object", "properties": properties, "required": required}


class Client:
    def __init__(self, *, lease_error=None):
        scalar = {"type": "string"}
        self.catalog = {"revision": "r7", "operations": [
            {"name": "work.public.list-v1", "repo_scoped": True, "execution_semantics": "read",
             "input_schema": schema({}, []),
             "result_schema": schema({"items": {"type": "array", "items": scalar}}, ["items"])},
            {"name": "work.public.item-v1", "repo_scoped": True, "execution_semantics": "read",
             "input_schema": schema({"work_id": {"type": "integer"}}, ["work_id"]),
             "result_schema": schema({"state": scalar}, ["state"])},
            {"name": "work.run.resolve-v1", "repo_scoped": True, "execution_semantics": "read",
             "input_schema": schema({"run_id": scalar}, ["run_id"]),
             "result_schema": schema({"run": scalar}, ["run"])},
            {"name": "work.lease.read-v1", "repo_scoped": True, "execution_semantics": "read",
             "input_schema": schema({"item_id": {"type": "integer"}}, ["item_id"]),
             "result_schema": schema({"lease": scalar}, ["lease"])},
            {"name": "work.evidence.tail-v1", "repo_scoped": True, "execution_semantics": "read",
             "input_schema": schema({"run_id": scalar}, ["run_id"]),
             "result_schema": schema({"tail": scalar}, ["tail"])},
        ]}
        self.calls, self.lease_error = [], lease_error

    def discover(self): return self.catalog
    def envelope(self, operation, arguments, key): return {"operation": operation, "arguments": arguments}
    def invoke(self, envelope):
        self.calls.append(envelope)
        if envelope["operation"] == "work.lease.read-v1" and self.lease_error:
            raise CoordinationError(self.lease_error)
        return {"work.public.list-v1": {"items": ["first", "second"]},
                "work.public.item-v1": {"state": "awaiting-verification"},
                "work.run.resolve-v1": {"run": "ok"}, "work.lease.read-v1": {"lease": "active"},
                "work.evidence.tail-v1": {"tail": "e9"}}[envelope["operation"]]


def test_snapshot_uses_catalog_argument_names_and_result_schema():
    client = Client()
    result = lifecycle(client, item_id=44, run_id="run_0123456789ABCDEFGHJKMNPQRS")
    assert [call["arguments"] for call in client.calls] == [
        {"work_id": 44}, {"run_id": "run_0123456789ABCDEFGHJKMNPQRS"},
        {"item_id": 44}, {"run_id": "run_0123456789ABCDEFGHJKMNPQRS"}]
    assert all(fact["state"] == "observed" and fact["revision"] == "r7"
               for fact in result["facts"].values())


def test_denied_lease_is_explicitly_unknown_not_no_lease():
    result = lifecycle(Client(lease_error="owner refused: runner-operation-denied (HTTP 403)"),
                       item_id=44, run_id="run_x")
    lease = result["facts"]["work.lease.read-v1"]
    assert lease["state"] == "unknown" and "runner-operation-denied" in lease["reason"]
    assert {reason["code"] for reason in attention_reasons(result)} >= {"owner-unknown", "lease-unknown"}


def test_missing_identifiers_are_unknown_and_never_an_empty_fact():
    result = lifecycle(Client(), item_id=44)
    assert result["facts"]["work.run.resolve-v1"]["state"] == "unknown"
    assert result["facts"]["work.run.resolve-v1"]["reason"] == "no run identifier available"


def test_ready_list_preserves_owner_order_without_a_local_ranking():
    fact = ready_work(Client())
    assert fact["state"] == "observed"
    assert fact["value"]["items"] == ["first", "second"]
