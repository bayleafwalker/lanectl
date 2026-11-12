"""Known query facts must reach the permalink without inventing identities."""
from lanectl.contracts import make_event
from lanectl.lifecycle import lifecycle_rows
from lanectl.lifecycle_web import locator, render_lifecycle, resolve_locator
from tests.stage9.test_lifecycle import Client, schema


class Owner(Client):
    def __init__(self, *, lease=None, item_work=None):
        super().__init__()
        self.lease, self.item_work = lease, item_work
        for operation in self.catalog["operations"]:
            if operation["name"] == "work.lease.read-v1":
                operation["result_schema"] = schema({}, ["lease"])

    def invoke(self, envelope):
        operation = envelope["operation"]
        if operation == "work.lease.read-v1" and self.lease is not None:
            self.calls.append(envelope)
            return {"lease": self.lease}
        if operation == "work.public.item-v1" and self.item_work is not None:
            self.calls.append(envelope)
            return dict(authority="sprintctl", state="ok", item=dict(work_id=self.item_work))
        return super().invoke(envelope)


def events(receipt=False):
    claim = make_event("item.claimed", dict(attempt_id="aa-a1", lane="implement", model="m",
        worker="w", source_session="session-x"), item_id="aa")
    if receipt:
        return [claim, make_event("item.landed", dict(attempt_id="aa-a1",
            train_id="train-landed", fix_commits=[]), item_id="aa")]
    return [claim, make_event("train.built", dict(train_id="train-x", base_sha="base",
        attempts=["aa-a1"], checked_sha="merged", passed=True))]


def test_known_query_facts_reach_permalink_and_page_without_invention():
    owner = Owner(lease=dict(lease_id="lease-x", item_id=2895, state="active"))
    row = lifecycle_rows(owner, events(), work_ids={"aa": 2895}, run_id="run-x")[0]
    assert (row["train_id"], row["lease_id"], row["source_session"]) == (
        "train-x", "lease-x", "session-x")
    resolved = resolve_locator(locator("lanectl", row))
    assert resolved["lease_id"] == "lease-x"
    assert resolved["source_session"] == "session-x" and resolved["train_id"] == "train-x"
    page = render_lifecycle("lanectl", row)
    assert "lease-x" in page and "session-x" in page
    plain = dict(row, lease_id=None, source_session=None)
    assert set(resolve_locator(locator("lanectl", plain))) == {
        "repo", "item_id", "attempt_id", "run_id", "train_id", "work_id"}


def test_train_id_falls_back_to_a_matching_landing_receipt():
    row = lifecycle_rows(Owner(lease=dict(lease_id="lease-x")), events(receipt=True),
                         work_ids={"aa": 2895})[0]
    assert row["train_id"] == "train-landed"


def test_owner_work_id_mismatch_stays_unknown_and_legacy_read_is_kept():
    bad = lifecycle_rows(Owner(item_work=999), events(), work_ids={"aa": 2895})[0]
    fact = bad["facts"]["work.public.item-v1"]
    assert fact["state"] == "unknown" and "mismatch" in fact["reason"].lower()
    assert bad["work_id"] == 2895 and bad["item_id"] == "aa"
    legacy = lifecycle_rows(Owner(), events(), work_ids={"aa": 2895})[0]
    assert legacy["facts"]["work.public.item-v1"]["state"] == "observed"
