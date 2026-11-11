"""UI-01 local lifecycle projections and UI-02 pure reason classification."""
import json
from datetime import datetime, timezone

from lanectl.contracts import make_event
from lanectl.events import EventLog
from lanectl.lifecycle import _cmd, attention_reasons, lifecycle_rows
from test_lifecycle import Client


def ev(kind, data, item=None, ts="2026-11-01T00:00:00Z"):
    return make_event(kind, data, item_id=item, ts=ts)


def test_rows_keep_mismatched_owner_and_local_identifiers_explicit():
    events = [ev("item.claimed", {"attempt_id": "a-one", "lane": "implement", "model": "m", "worker": "w"}, "local-item")]
    row = lifecycle_rows(Client(), events, item_id="local-item")[0]
    assert row["item_id"] == "local-item"
    assert row["facts"]["work.public.item-v1"]["state"] == "unknown"  # owner schema wants an integer
    fact = row["facts"]["local.attempt"]
    assert fact["source"] == "lanectl.events" and fact["checkpoint"] == 1
    assert fact["value"][0]["data"]["attempt_id"] == "a-one"


def test_stale_and_partial_lifecycle_reasons_are_explicit():
    events = [ev("item.claimed", {"attempt_id": "a-one", "lane": "implement", "model": "m", "worker": "w"}, "item-1"),
              ev("item.landed", {"attempt_id": "a-one", "train_id": "t-one", "fix_commits": []}, "item-1")]
    row = lifecycle_rows(Client(), events, item_id="item-1")[0]
    codes = {r["code"] for r in attention_reasons(row, now=datetime(2026, 11, 2, tzinfo=timezone.utc), stale_after_s=1)}
    assert {"reconcile", "stale-deploy", "lease-uncertainty"} <= codes


def test_reason_table_covers_gate_revalidation_and_pending_verification():
    events = [ev("item.claimed", {"attempt_id": "a-one", "lane": "implement", "model": "m", "worker": "w"}, "item-1"),
              ev("attempt.finished", {"attempt_id": "a-one", "outcome": "ok", "exit_code": 0, "head_sha": "head"}, "item-1"),
              ev("gate.result", {"attempt_id": "a-one", "gate": "test", "passed": False, "violations": []}, "item-1"),
              ev("train.built", {"train_id": "t-one", "base_sha": "base", "attempts": ["a-one"], "passed": True}, ts="2026-11-01T00:01:00Z")]
    row = lifecycle_rows(Client(), events, item_id="item-1")[0]
    reasons = attention_reasons(row)
    codes = {r["code"] for r in reasons}
    assert {"gate-failure", "revalidation"} <= codes
    pending = attention_reasons({"facts": {"work.public.item-v1": {
        "state": "observed", "value": {"state": "awaiting-verification"}}}})
    assert pending[0]["code"] == "pending-verification"
    assert all(r["evidence"] and r["next_actions"] for r in reasons if r["code"] != "lease-unknown")


def test_cli_json_and_table_use_same_fake_snapshot(tmp_path, capsys):
    log = EventLog(tmp_path / "events.jsonl")
    log.append("item.claimed", {"attempt_id": "a-one", "lane": "implement", "model": "m", "worker": "w"}, item_id="item-1")
    class Args: repo, item, json = "repo", "item-1", False
    assert _cmd(Args(), log, client=Client()) == 0
    assert "ITEM  ATTEMPT" in capsys.readouterr().out
    Args.json = True
    assert _cmd(Args(), log, client=Client()) == 0
    assert json.loads(capsys.readouterr().out)["rows"][0]["attempt_id"] == "a-one"
