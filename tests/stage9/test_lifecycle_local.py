"""UI-01 local lifecycle projections and UI-02 pure reason classification."""
import json
from datetime import datetime, timezone
import builtins
import socket

import pytest

from lanectl.contracts import make_event
from lanectl.events import EventLog
from lanectl.lifecycle import REASON_RULES, _cmd, attention_reasons, lifecycle_rows
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
    json_rows = json.loads(capsys.readouterr().out)["rows"]
    assert len(json_rows) == 1
    assert json_rows[0]["item_id"] == "item-1"
    assert json_rows[0]["attempt_id"] == "a-one"
    assert json_rows[0]["reasons"]
    assert all(reason["rule"] == REASON_RULES[reason["code"]] and reason["next_actions"]
               for reason in json_rows[0]["reasons"])


def _fact(name, value, *, state="observed", observed_at="2026-11-01T00:00:00Z"):
    return {"state": state, "source": name, "revision": "r1", "observed_at": observed_at,
            **({"value": value} if state == "observed" else {})}


def _event(kind, data):
    return {"type": kind, "item_id": "item-1", "ts": "2026-11-01T00:00:00Z", "data": data}


REASON_CASES = [
    ("lease-uncertainty", {"work.lease.read-v1": _fact("work.lease.read-v1", {}, state="unknown")},
     "work.lease.read-v1", "item_id"),
    ("revalidation", {"local.train": _fact("local.train", [_event("train.built", {
        "train_id": "train-1", "passed": True, "checked_sha": "old"})]),
        "local.attempt": _fact("local.attempt", [_event("attempt.finished", {
            "attempt_id": "attempt-1", "head_sha": "new"})])}, "local.train", "train_id"),
    ("gate-failure", {"local.attempt": _fact("local.attempt", [_event("gate.result", {
        "attempt_id": "attempt-1", "gate": "tests", "passed": False})])}, "local.attempt", "attempt_id"),
    ("stale-deploy", {"local.train": _fact("local.train", [], observed_at="2026-11-01T00:00:00Z")},
     "local.train", "observed_at"),
    ("pending-verification", {"work.public.item-v1": _fact("work.public.item-v1", {
        "state": "awaiting-verification"})}, "work.public.item-v1", "item_id"),
    ("reconcile", {"local.receipt": _fact("local.receipt", [_event("item.landed", {
        "attempt_id": "attempt-1", "train_id": "train-1", "fix_commits": []})])},
     "local.receipt", "attempt_id"),
    ("owner-unknown", {"work.run.resolve-v1": _fact("work.run.resolve-v1", {}, state="unknown")},
     "work.run.resolve-v1", "run_id"),
]


@pytest.mark.parametrize("code,facts,evidence_fact,identifier", REASON_CASES)
def test_each_reason_has_identified_evidence_and_a_healthy_negative(code, facts, evidence_fact, identifier):
    fixed_now = datetime(2026, 11, 2, tzinfo=timezone.utc)
    if code == "lease-uncertainty":
        facts[evidence_fact]["reason"] = "lease unavailable"
    reasons = attention_reasons({"item_id": "item-1", "run_id": "run-1", "facts": facts},
                                now=fixed_now, stale_after_s=1 if code == "stale-deploy" else None)
    reason = next(reason for reason in reasons if reason["code"] == code)
    assert reason["rule"] == REASON_RULES[code]
    assert reason["evidence"]
    evidence = reason["evidence"][0]
    assert evidence["fact"] == evidence_fact
    assert evidence["identifiers"].get(identifier)
    assert reason["next_actions"]

    healthy = {
        "work.lease.read-v1": _fact("work.lease.read-v1", {"lease": "active"}, observed_at="2026-11-02T00:00:00Z"),
        "work.public.item-v1": _fact("work.public.item-v1", {"state": "active"}, observed_at="2026-11-02T00:00:00Z"),
        "work.run.resolve-v1": _fact("work.run.resolve-v1", {"run": "ok"}, observed_at="2026-11-02T00:00:00Z"),
        "work.evidence.tail-v1": _fact("work.evidence.tail-v1", {"tail": "ok"}, observed_at="2026-11-02T00:00:00Z"),
        "local.attempt": _fact("local.attempt", [_event("attempt.finished", {
            "attempt_id": "attempt-1", "outcome": "ok", "head_sha": "head"})], observed_at="2026-11-02T00:00:00Z"),
        "local.train": _fact("local.train", [_event("train.built", {
            "train_id": "train-1", "passed": True, "checked_sha": "head"})], observed_at="2026-11-02T00:00:00Z"),
        "local.receipt": _fact("local.receipt", [], observed_at="2026-11-02T00:00:00Z"),
    }
    negative = attention_reasons({"item_id": "item-1", "run_id": "run-1", "facts": healthy},
                                now=fixed_now, stale_after_s=1)
    assert code not in {reason["code"] for reason in negative}


def test_attention_reasons_is_pure_and_deterministic(monkeypatch):
    snapshot = {"facts": {"local.train": _fact("local.train", [], observed_at="2026-11-01T00:00:00Z")}}
    def forbidden(*args, **kwargs):
        raise AssertionError("attention_reasons attempted I/O")
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    kwargs = {"now": datetime(2026, 11, 2, tzinfo=timezone.utc), "stale_after_s": 1}
    first = attention_reasons(snapshot, **kwargs)
    assert attention_reasons(snapshot, **kwargs) == first


def test_cli_table_has_one_row_each_reason_codes_and_unknown_owner_label(tmp_path, capsys):
    log = EventLog(tmp_path / "events.jsonl")
    log.append("item.claimed", {"attempt_id": "a-one", "lane": "implement", "model": "m", "worker": "w"}, item_id="item-1")
    class Args: repo, item, json = "repo", "item-1", False
    assert _cmd(Args(), log, client=Client()) == 0
    output = capsys.readouterr().out
    lines = output.splitlines()
    assert len(lines) == 2  # header plus one lifecycle row
    assert "a-one" in lines[1]
    assert "owner-unknown" in lines[1]
    assert "unknown" in lines[1]
