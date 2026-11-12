from copy import deepcopy
from datetime import datetime, timezone

from lanectl.contracts import make_event
from lanectl.verification import evidence_bundle, render_bundle


def fact(value, source="lanectl.events"):
    return dict(state="observed", source=source, revision="r7", checkpoint=12,
                observed_at="2026-11-12T10:00:00Z", value=value)


def row():
    return dict(item_id="ui-work", attempt_id="ui-work-a1", facts={
        "local.attempt": fact([make_event("gate.result", dict(
            attempt_id="ui-work-a1", gate="suite", passed=True, violations=[]))]),
        "local.train": fact([
            make_event("train.built", dict(train_id="tr-12", base_sha="base",
                attempts=["ui-work-a1"], passed=True, checked_sha="abc")),
            make_event("train.deployed", dict(train_id="tr-12", repo="lanectl",
                namespace="lane-dev-tr-12", passed=True, checked_sha="abc",
                expires_at="2026-11-12T12:00:00Z"))]),
        "local.receipt": fact([
            make_event("item.landed", dict(attempt_id="ui-work-a1", train_id="tr-12",
                fix_commits=[], landed_sha="abc")),
            make_event("work.synced", dict(work="lanectl#2896", train_id="tr-12",
                closed=False, ok=True, owner_reported=True, pending_owner=True))]),
        "work.public.item-v1": fact(dict(authority="sprintctl", state="ok",
            as_of="2026-11-12T10:00:00Z", item=dict(work_id=2896,
            status="awaiting-verification", resolution=None)), "work.public.item-v1"),
        "work.evidence.tail-v1": fact(dict(item=dict(chain_seq=2,
            ref="lane://lanectl/train/tr-12", body="secret raw output",
            reference="https://example.test/receipt?token=secret")), "work.evidence.tail-v1")})


NOW = datetime(2026, 11, 12, 11, tzinfo=timezone.utc)


def entries(bundle):
    return {entry["kind"]: entry for entry in bundle["entries"]}


def test_receipts_are_pending_until_fresh_owner_acceptance():
    snapshot = row()
    before = deepcopy(snapshot)
    bundle = evidence_bundle(snapshot, now=NOW)
    assert snapshot == before
    assert bundle["outcome"] != "accepted"
    by_kind = entries(bundle)
    assert set(by_kind) == {"gates", "checked-commit", "deploy", "landing",
                            "evidence-chain", "outcome-report", "owner-decision"}
    for kind in ("gates", "checked-commit", "deploy", "landing"):
        assert by_kind[kind]["state"] == "observed"
        assert by_kind[kind]["source"] == "lanectl.events"
        assert by_kind[kind]["checkpoint"] == 12
        assert by_kind[kind]["revision"] == "r7"
        assert by_kind[kind]["observed_at"]
    snapshot["facts"]["work.public.item-v1"]["value"]["item"].update(
        status="done", resolution="completed")
    assert evidence_bundle(snapshot, now=NOW)["outcome"] == "accepted"


def test_unknown_missing_rejected_and_stale_are_different():
    snapshot = row()
    snapshot["facts"]["local.attempt"]["value"][0]["data"]["passed"] = False
    snapshot["facts"]["local.train"]["value"][1]["data"]["expires_at"] = "2026-11-12T10:59:00Z"
    snapshot["facts"]["local.receipt"]["value"] = []
    snapshot["facts"]["work.public.item-v1"] = dict(state="unknown", source="owner", reason="offline")
    bundle = evidence_bundle(snapshot, now=NOW)
    states = entries(bundle)
    assert states["gates"]["state"] == "rejected"
    assert states["deploy"]["state"] == "stale"
    assert states["landing"]["state"] == "missing"
    assert states["owner-decision"]["state"] == "unknown"
    assert bundle["outcome"] != "accepted"
    assert all(word in render_bundle(bundle) for word in ("rejected", "stale", "missing", "unknown"))


def test_sha_mismatch_and_missing_checked_sha_do_not_look_verified():
    snapshot = row()
    snapshot["facts"]["local.train"]["value"][1]["data"]["checked_sha"] = "other"
    snapshot["facts"]["local.receipt"]["value"][0]["data"]["landed_sha"] = "other"
    states = entries(evidence_bundle(snapshot, now=NOW))
    assert states["deploy"]["state"] == "stale"
    assert states["landing"]["state"] == "stale"
    del snapshot["facts"]["local.train"]["value"][0]["data"]["checked_sha"]
    assert entries(evidence_bundle(snapshot, now=NOW))["checked-commit"]["state"] == "missing"


def test_refs_and_text_do_not_publish_raw_evidence_or_secret_locators():
    bundle = evidence_bundle(row(), now=NOW)
    refs = [ref for entry in bundle["entries"] for ref in entry["references"]]
    assert "lane://lanectl/train/tr-12" in refs
    assert not any("token=" in ref for ref in refs)
    text = render_bundle(bundle)
    assert "secret raw output" not in text
    assert "token=secret" not in text
    assert "source=" in text and "observed" in text
