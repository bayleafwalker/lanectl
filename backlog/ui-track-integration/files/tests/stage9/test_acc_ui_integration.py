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


def test_owner_read_clock_does_not_make_a_preview_impossible_to_execute(monkeypatch):
    from lanectl import claim_preview as cp
    from tests.stage9.test_acc_claim_preview import config, Owner
    release, lane, repos = config(monkeypatch)
    owner = Owner()
    first = cp.preview_claim(owner, release, lane, repos)
    owner.value["as_of"] = "2026-11-12T10:00:05Z"
    assert cp.preview_claim(owner, release, lane, repos)["digest"] == first["digest"]
    owner.value["item"]["status"] = "active"
    assert cp.preview_claim(owner, release, lane, repos)["digest"] != first["digest"]


def test_conflicting_journal_never_joins_another_owners_work(tmp_path):
    import sqlite3
    import json
    journal = tmp_path / "binding.sqlite"
    with sqlite3.connect(journal) as db:
        db.execute("CREATE TABLE bindings (attempt TEXT, binding TEXT)")
        db.execute("INSERT INTO bindings VALUES (?, ?)", ("ui-work-a1",
                   json.dumps({"item_id": 999, "run_id": "run-wrong"})))
    events = [make_event("item.claimed", dict(attempt_id="ui-work-a1", lane="implement",
                         model="model-a", worker="fake"), item_id="ui-work")]
    owner = RealOwner()
    row = lifecycle_rows(owner, events, work_ids={"ui-work": 2895}, journal_path=journal)[0]
    assert row["facts"]["work.public.item-v1"]["state"] == "unknown"
    assert "mismatch" in row["facts"]["work.public.item-v1"].get("reason", "").lower()
    assert not any(call["operation"] == "work.public.item-v1" for call in owner.calls)


def test_tui_sources_never_publish_raw_paths_or_secret_query_refs():
    row = {"item_id": "ui-work", "facts": {"local.receipt": {
        "state": "observed", "source": "lanectl.events", "value": [{"data": {
            "body": "private transcript at /home/user/private", "ref": "https://example.test/r?token=secret",
            "reference": "https://example.test/safe"}}]}}}
    text = "\n".join(tui.source_lines(row))
    assert "private transcript" not in text and "/home/user/private" not in text
    assert "token=secret" not in text
    assert "https://example.test/safe" in text


def test_preview_binds_release_semantics_and_owner_audience(monkeypatch):
    from dataclasses import replace
    from lanectl import claim_preview as cp
    from tests.stage9.test_acc_claim_preview import config, Owner
    release, lane, repos = config(monkeypatch)
    owner = Owner()
    owner.endpoint, owner.repo_id = "https://owner.example.test", "repo-a"
    preview = cp.preview_claim(owner, release, lane, repos)
    changed = replace(release, outcome=release.outcome + " changed")
    assert cp.preview_claim(owner, changed, lane, repos)["digest"] != preview["digest"]
    owner.repo_id = "repo-b"
    assert cp.preview_claim(owner, release, lane, repos)["digest"] != preview["digest"]


def test_real_deploy_events_join_by_train_without_equating_attempt_and_train_shas():
    events = [make_event("item.claimed", dict(attempt_id="ui-work-a1", lane="implement",
                         model="model-a", worker="fake"), item_id="ui-work"),
        make_event("attempt.finished", dict(attempt_id="ui-work-a1", outcome="done", exit_code=0,
                   head_sha="attempt-commit"), item_id="ui-work"),
        make_event("train.built", dict(train_id="train-right", base_sha="base",
                   attempts=["ui-work-a1"], passed=True, checked_sha="merged-train-commit")),
        make_event("train.deployed", dict(train_id="train-right", repo="lanectl", namespace="dev",
                   passed=True, checked_sha="merged-train-commit", expires_at="2099-01-01T00:00:00Z")),
        make_event("train.deployed", dict(train_id="train-other", repo="lanectl", namespace="other",
                   passed=False, checked_sha="other", expires_at="2099-01-01T00:00:00Z"))]
    row = lifecycle_rows(RealOwner(), events, work_ids={"ui-work": 2895})[0]
    trains = row["facts"]["local.train"]["value"]
    assert [e["data"]["train_id"] for e in trains] == ["train-right", "train-right"]
    assert "revalidation" not in {r["code"] for r in attention_reasons(row)}
    from lanectl.verification import evidence_bundle, render_bundle
    bundle = evidence_bundle(row)
    text = render_bundle(bundle)
    assert "merged-train-commit" in text and "train-right" in text
    assert "2099-01-01T00:00:00Z" in text


def test_web_roundtrips_owner_work_and_excludes_runtime_payload_references():
    from lanectl.lifecycle_web import locator, resolve_locator, render_lifecycle
    row = dict(item_id="ui-work", work_id=2895, attempt_id="ui-work-a1", facts={
        "work.evidence.tail-v1": {"state": "observed", "source": "owner", "value": {
            "item": {"ref": "https://example.test/safe", "body": {
                "ref": "https://example.test/private-runtime-body"}}}}})
    assert resolve_locator(locator("lanectl", row))["work_id"] == 2895
    text = render_lifecycle("lanectl", row)
    assert "2895" in text and "https://example.test/safe" in text
    assert "private-runtime-body" not in text
    row["facts"]["work.evidence.tail-v1"]["value"]["item"]["ref"] = "https://[invalid"
    assert "snapshot" in render_lifecycle("lanectl", row)
