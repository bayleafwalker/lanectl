from copy import deepcopy
from types import SimpleNamespace

from lanectl.contracts import make_event
from lanectl.lifecycle import lifecycle_rows, attention_reasons
from lanectl import tui
from tests.stage9.test_lifecycle import Client, schema


class RealOwner(Client):
    def __init__(self):
        super().__init__()
        for operation in self.catalog["operations"]:
            if operation["name"] in ("work.public.item-v1", "work.public.list-v1"):
                operation["result_schema"] = schema({}, [])
    def invoke(self, envelope):
        self.calls.append(envelope)
        if envelope["operation"] == "work.public.item-v1":
            assert envelope["arguments"] == {"work_id": 2895}
            return dict(authority="sprintctl", state="ok", as_of="2026-11-12T10:00:00Z",
                        item=dict(work_id=2895, status="awaiting-verification", resolution=None))
        if envelope["operation"] == "work.public.list-v1":
            return {"items": [{"work_id": 2895, "status": "pending"}]}
        return super().invoke(envelope)


def test_release_and_owner_identity_remain_distinct_but_joined():
    events = [make_event("item.claimed", dict(attempt_id="ui-work-a1", lane="implement",
                         model="model-a", worker="fake"), item_id="ui-work")]
    owner = RealOwner()
    rows = lifecycle_rows(owner, events, work_ids={"ui-work": 2895})
    assert len(rows) == 1
    row = rows[0]
    assert row["item_id"] == "ui-work" and row["work_id"] == 2895
    assert row["facts"]["local.attempt"]["value"][0]["item_id"] == "ui-work"
    assert row["facts"]["work.public.item-v1"]["state"] == "observed"
    assert "pending-verification" in {r["code"] for r in attention_reasons(row)}
    snapshot = tui.build_snapshot(dict(state="observed", source="work.public.list-v1",
        value={"items": [{"work_id": 2895, "status": "pending"}]}), rows)
    assert tui.view_rows(snapshot, tui.READY)[0]["attempt_id"] == "ui-work-a1"
    text = tui.render_plain_table(snapshot, tui.VERIFICATION)
    assert "awaiting-verification" in text and "ui-work" in text


def test_owner_acceptance_uses_existing_protocol_not_completed_resolution():
    from lanectl.verification import evidence_bundle
    row = dict(item_id="ui-work", work_id=2895, facts={"work.public.item-v1": {
        "state": "observed", "source": "work.public.item-v1", "revision": "r7",
        "observed_at": "2026-11-12T10:00:00Z", "value": dict(authority="sprintctl",
        state="ok", as_of="2026-11-12T10:00:00Z", item=dict(work_id=2895,
        status="done", resolution="accepted"))}})
    assert evidence_bundle(row)["outcome"] == "accepted"
    for resolution in ("completed", "rejected", "withdrawn", None):
        changed = deepcopy(row)
        changed["facts"]["work.public.item-v1"]["value"]["item"]["resolution"] = resolution
        assert evidence_bundle(changed)["outcome"] != "accepted"
    changed = deepcopy(row)
    changed["facts"]["work.public.item-v1"]["value"]["item"]["work_id"] = 999
    assert evidence_bundle(changed)["outcome"] != "accepted"


def test_claim_path_never_falls_back_to_native_when_coordination_disappears(monkeypatch):
    from lanectl import runner, coordination
    calls = []
    monkeypatch.setattr(coordination, "configured", lambda *args: None)
    monkeypatch.setattr(runner, "_coordination_park", lambda *args: "coordination refused")
    wrapped = runner._coordinate_execution(lambda *args: calls.append("native"))
    claim = SimpleNamespace(repo=SimpleNamespace(name="lanectl"))
    log = SimpleNamespace(read=lambda: [])
    result = wrapped(claim, log, require_coordination=True)
    assert calls == [] and "refused" in result
