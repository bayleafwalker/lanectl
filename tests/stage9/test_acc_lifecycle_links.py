from lanectl.contracts import make_event
from lanectl.lifecycle import lifecycle_rows
from lanectl.lifecycle_web import locator, resolve_locator, render_lifecycle
from tests.stage9.test_acc_ui_integration import RealOwner


class LinkedOwner(RealOwner):
    def __init__(self, wrong_work=False):
        super().__init__()
        self.wrong_work = wrong_work
        for operation in self.catalog["operations"]:
            if operation["name"] == "work.lease.read-v1":
                operation["result_schema"] = {"type": "object", "properties": {}, "required": ["lease"]}
    def invoke(self, envelope):
        if envelope["operation"] == "work.lease.read-v1":
            return {"lease": {"lease_id": "lease-smoke", "item_id": 2895, "run_id": "run-smoke", "state": "active"}}
        result = super().invoke(envelope)
        if self.wrong_work and envelope["operation"] == "work.public.item-v1":
            result["item"]["work_id"] = 999
        return result


def events():
    return [make_event("item.claimed", dict(attempt_id="aa-a1", lane="implement", model="model-a",
        worker="fake", source_session="session-smoke"), item_id="aa"),
        make_event("train.built", dict(train_id="train-smoke", base_sha="base", attempts=["aa-a1"],
        checked_sha="merged-abc", passed=True))]


def test_real_query_links_reach_the_permalink_and_page():
    row = lifecycle_rows(LinkedOwner(), events(), work_ids={"aa": 2895}, run_id="run-smoke")[0]
    assert row.get("train_id") == "train-smoke" and row.get("lease_id") == "lease-smoke"
    assert row.get("source_session") == "session-smoke"
    resolved = resolve_locator(locator("lanectl", row))
    assert resolved.get("train_id") == "train-smoke" and resolved.get("work_id") == 2895
    assert resolved.get("lease_id") == "lease-smoke" and resolved.get("source_session") == "session-smoke"
    page = render_lifecycle("lanectl", row)
    assert all(value in page for value in ("lease-smoke", "session-smoke", "train-smoke"))


def test_foreign_owner_item_is_unknown_and_never_rebinds_local_identity():
    row = lifecycle_rows(LinkedOwner(wrong_work=True), events(), work_ids={"aa": 2895})[0]
    fact = row["facts"]["work.public.item-v1"]
    assert fact["state"] == "unknown" and "mismatch" in fact.get("reason", "").lower()
    assert row["work_id"] == 2895 and row["item_id"] == "aa"
