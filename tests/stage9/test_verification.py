"""Evidence bundle projection: nested owner shapes, partial history, commit
mismatch, safe references, snapshot immutability and the verify command."""
from copy import deepcopy
from datetime import datetime, timezone

from lanectl.contracts import make_event
from lanectl.verification import evidence_bundle, render_bundle

NOW = datetime(2026, 11, 12, 11, tzinfo=timezone.utc)


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


def entries(bundle):
    return {entry["kind"]: entry for entry in bundle["entries"]}


def test_nested_owner_shapes_distinguish_accepted_rejected_and_pending():
    snapshot = row()
    assert evidence_bundle(snapshot, now=NOW)["outcome"] == "pending"

    snapshot["facts"]["work.public.item-v1"]["value"]["item"].update(
        status="done", resolution="completed")
    accepted = evidence_bundle(snapshot, now=NOW)
    assert accepted["outcome"] == "accepted"
    assert entries(accepted)["owner-decision"]["state"] == "observed"

    snapshot["facts"]["work.public.item-v1"]["value"]["item"].update(
        status="done", resolution="rejected")
    rejected = evidence_bundle(snapshot, now=NOW)
    assert entries(rejected)["owner-decision"]["state"] == "rejected"
    assert rejected["outcome"] == "rejected"


def test_unavailable_owner_never_implies_acceptance():
    snapshot = row()
    snapshot["facts"]["work.public.item-v1"] = dict(
        state="unknown", source="owner", reason="offline")
    bundle = evidence_bundle(snapshot, now=NOW)
    assert entries(bundle)["owner-decision"]["state"] == "unknown"
    assert bundle["outcome"] == "unknown"


def test_partial_history_missing_deploy_does_not_invalidate_landing():
    snapshot = row()
    snapshot["facts"]["local.train"]["value"] = [snapshot["facts"]["local.train"]["value"][0]]
    bundle = evidence_bundle(snapshot, now=NOW)
    by_kind = entries(bundle)
    assert by_kind["deploy"]["state"] == "missing"
    assert by_kind["landing"]["state"] == "observed"
    assert bundle["outcome"] != "accepted"


def test_partial_history_missing_receipts_are_missing():
    snapshot = row()
    snapshot["facts"]["local.receipt"]["value"] = []
    by_kind = entries(evidence_bundle(snapshot, now=NOW))
    assert by_kind["landing"]["state"] == "missing"
    assert by_kind["outcome-report"]["state"] == "missing"


def test_commit_mismatch_is_stale_not_verified():
    snapshot = row()
    snapshot["facts"]["local.train"]["value"][1]["data"]["checked_sha"] = "other"
    snapshot["facts"]["local.receipt"]["value"][0]["data"]["landed_sha"] = "other"
    bundle = evidence_bundle(snapshot, now=NOW)
    by_kind = entries(bundle)
    assert by_kind["deploy"]["state"] == "stale"
    assert by_kind["landing"]["state"] == "stale"
    assert bundle["outcome"] == "stale"


def test_safe_references_preserve_clean_locators_and_drop_secrets():
    snapshot = row()
    snapshot["facts"]["work.evidence.tail-v1"]["value"]["item"]["reference"] = \
        "https://example.test/receipt"
    refs = [ref for entry in evidence_bundle(snapshot, now=NOW)["entries"]
            for ref in entry["references"]]
    assert "lane://lanectl/train/tr-12" in refs
    assert "https://example.test/receipt" in refs
    assert "secret raw output" not in refs
    assert not any("token=" in ref for ref in refs)


def test_bundle_never_mutates_the_snapshot():
    snapshot = row()
    before = deepcopy(snapshot)
    evidence_bundle(snapshot, now=NOW)
    assert snapshot == before


def test_render_bundle_lists_every_entry_and_the_outcome():
    snapshot = row()
    snapshot["facts"]["work.public.item-v1"]["value"]["item"].update(
        status="done", resolution="completed")
    text = render_bundle(evidence_bundle(snapshot, now=NOW))
    assert "outcome=accepted" in text
    for kind in ("gates", "checked-commit", "deploy", "landing",
                 "evidence-chain", "outcome-report", "owner-decision"):
        assert kind in text
    assert "source=" in text and "observed" in text


def test_verify_command_refuses_unconfigured_coordination(tmp_path, capsys, monkeypatch):
    from lanectl.events import EventLog
    from lanectl.verification import _cmd
    monkeypatch.setattr("lanectl.coordination.configured", lambda repo: None)
    log = EventLog(tmp_path / "events.jsonl")
    class Args:
        repo, item, json = "repo", "item-1", False
    assert _cmd(Args(), log) == 1
    assert "not configured" in capsys.readouterr().out


def test_verify_command_formats_bundles_with_a_fake_client(tmp_path, capsys):
    from lanectl.events import EventLog
    from lanectl.verification import _cmd
    from test_lifecycle import Client
    log = EventLog(tmp_path / "events.jsonl")
    log.append("item.claimed", {"attempt_id": "a-one", "lane": "implement",
                                "model": "m", "worker": "w"}, item_id="item-1")
    class Args:
        repo, item, json = "repo", "item-1", False
    assert _cmd(Args(), log, client=Client()) == 0
    out = capsys.readouterr().out
    assert "outcome=" in out
    assert "gates" in out
