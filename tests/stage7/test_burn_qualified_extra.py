"""Extra coverage: qualified burn checks, dwell and allocation decisions."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from lanectl import burn, capacity
from lanectl.contracts import make_event
from lanectl.events import EventLog

NOW = datetime(2026, 11, 9, 14, 30, tzinfo=timezone.utc)
CAPS = {"concurrency": 3, "items_per_day": 48, "accepted_unlanded_max": 8}
READY = [("aa", "S"), ("bb", "S")]


def _raw(basis="verified", **allocation):
    return {
        "revision": 7,
        "burn": {"start_within_s": 3600, "min_burnable": 10000},
        "allocation": {"min_dwell_s": 1800, "change_threshold": 0.2, **allocation},
        "providers": {"opencode": {
            "unit": "output_tokens", "expiring": True, "pool": "p:1",
            "freshness_s": 3600, "estimates": {"S": 15000},
            "windows": [{"name": "5h", "length_s": 18000, "budget": 100000,
                         "anchor": "2026-11-09T10:00:00Z", "budget_basis": basis}]}},
    }


def _usage(value, at="2026-11-09T11:00:00Z"):
    return make_event("usage.recorded", {
        "provider": "opencode", "source": "adapter",
        "units": {"output_tokens": value}}, ts=at)


def _obs(value=10000, at="2026-11-09T14:20:00Z"):
    return make_event("capacity.observed", {
        "provider": "opencode", "pool": "p:1", "source": "opencode-stats",
        "unit": "output_tokens", "basis": "measured", "observed_at": at, "value": value,
        "value_kind": "cumulative", "window_start": "2026-11-09T10:00:00Z"}, ts=at)


def _deny():
    return make_event("capacity.observed", {
        "provider": "opencode", "pool": "p:1", "source": "window-detector",
        "unit": "output_tokens", "basis": "measured", "observed_at": "2026-11-09T14:25:00Z",
        "value": None, "value_kind": "denial", "reset_at": "2026-11-09T15:00:00Z"},
        ts="2026-11-09T14:25:00Z")


def _reserved(amount=5000):
    return make_event("capacity.reserved", {
        "reservation_id": "res-1", "provider": "opencode", "pool": "p:1",
        "unit": "output_tokens", "amount": amount, "attempt_id": "aa-a1"},
        ts="2026-11-09T14:10:00Z")


def _applied(burnable=88000, age_s=600):
    return make_event("lane.decision", {
        "decision_id": "dec-1", "kind": "allocation", "phase": "applied",
        "chosen": "aa", "mechanism": "burn-plan/v1", "policy_revision": "allocation@7",
        "burnable": burnable},
        ts=(NOW - timedelta(seconds=age_s)).strftime("%Y-%m-%dT%H:%M:%SZ"))


def _decisions(log, **match):
    return [e["data"] for e in log.read() if e["type"] == "lane.decision"
            and all(e["data"].get(k) == v for k, v in match.items())]


def test_budget_basis_defaults_to_placeholder_and_rejects_unknown_values():
    raw = {"revision": 1, "providers": {"p": {
        "unit": "tokens", "windows": [{"name": "w", "length_s": 60, "budget": 10}]}}}
    policy = capacity.AllocationPolicy.from_dict(raw)
    assert policy.providers["p"].windows[0].budget_basis == "placeholder"

    bad = {"revision": 1, "providers": {"p": {
        "unit": "tokens",
        "windows": [{"name": "w", "length_s": 60, "budget": 10,
                     "budget_basis": "assumed"}]}}}
    with pytest.raises(capacity.PolicyError):
        capacity.AllocationPolicy.from_dict(bad)


def test_check_blocks_placeholder_unknown_and_denied_capacity():
    placeholder = burn.check([_obs()], _raw("placeholder"), NOW)
    assert any("placeholder" in r for r in placeholder)

    unknown = burn.check([], _raw(), NOW)
    assert any("unknown" in r for r in unknown)

    denied = burn.check([_obs(), _deny()], _raw(), NOW)
    assert any("denied" in r for r in denied)
    assert burn.plan_burn([_obs(), _deny()], _raw(), NOW, READY, CAPS, 0, 0) is None

    assert burn.check([_obs()], _raw(), NOW) == []


def test_plan_uses_measured_burnable_minus_outside_and_in_flight():
    events = [_usage(10000), _obs(20000), _reserved(5000)]
    plan = burn.plan_burn(events, _raw(), NOW, READY, CAPS, 0, 0)
    assert plan is not None
    assert plan["burnable"] == 100000 - 10000 - 10000 - 5000
    assert plan["items"] == ["aa", "bb"]


def test_dwell_blocks_a_small_change_only():
    small = burn.check([_obs(10000), _applied(88000)], _raw(), NOW)
    assert any("dwell" in r for r in small)
    assert burn.plan_burn([_obs(10000), _applied(88000)], _raw(), NOW,
                          READY, CAPS, 0, 0) is None

    # 40000 burnable is far below the recorded 88000: past the 20% threshold.
    large = burn.check([_obs(60000), _applied(88000)], _raw(), NOW)
    assert not any("dwell" in r for r in large)

    # The dwell only holds for min_dwell_s; 40 minutes later the held value is stale.
    expired = burn.check([_obs(10000), _applied(88000, age_s=2400)], _raw(), NOW)
    assert not any("dwell" in r for r in expired)


def test_denial_is_reported_even_inside_the_dwell():
    reasons = burn.check([_obs(), _applied(88000), _deny()], _raw(), NOW)
    assert any("dwell" in r for r in reasons)
    assert any("denied" in r for r in reasons)


def test_execute_records_the_proposal_and_correlates_applied_items(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    log.append("capacity.observed", _obs()["data"])
    plan = burn.plan_burn(log.read(), _raw(), NOW, READY, CAPS, 0, 0)

    claims = burn.execute_plan(log, plan, _raw(), NOW,
                               lambda rid: SimpleNamespace(attempt_id=f"{rid}-a1"))

    assert [c.attempt_id for c in claims] == ["aa-a1", "bb-a1"]
    proposed = _decisions(log, kind="allocation", phase="proposed")
    assert len(proposed) == 1
    prop = proposed[0]
    assert prop["chosen"] == "opencode/5h"
    assert prop["mechanism"] == "burn-plan/v1"
    assert prop["policy_revision"] == "allocation@7"
    assert prop["items"] == ["aa", "bb"] and prop["burnable"] == 90000
    assert prop["snapshot_ts"]
    applied = _decisions(log, kind="allocation", phase="applied")
    assert [a["subject"] for a in applied] == [
        {"item_id": "aa", "attempt_id": "aa-a1"},
        {"item_id": "bb", "attempt_id": "bb-a1"}]
    assert all(a["proposal_id"] == prop["decision_id"] for a in applied)


def test_execute_refuses_and_stops_when_admit_returns_a_reason(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    log.append("capacity.observed", _obs()["data"])
    plan = burn.plan_burn(log.read(), _raw(), NOW, READY, CAPS, 0, 0)
    called = []

    def admit(rid):
        called.append(rid)
        return "cap: concurrency 3/3"

    claims = burn.execute_plan(log, plan, _raw(), NOW, admit)

    assert claims == [] and called == ["aa"]     # stops at the first refusal
    refused = _decisions(log, kind="allocation", phase="refused")
    assert len(refused) == 1 and refused[0]["reasons"] == ["cap: concurrency 3/3"]
    assert refused[0]["proposal_id"] == _decisions(log, phase="proposed")[0]["decision_id"]
    assert _decisions(log, phase="applied") == []


def test_burn_command_prints_the_placeholder_reason(tmp_path, monkeypatch, capsys):
    (tmp_path / "governance").mkdir()
    (tmp_path / "governance" / "allocation.toml").write_text(
        'revision = 5\n\n[burn]\nstart_within_s = 3600\nmin_burnable = 10000\n\n'
        '[providers.opencode]\nunit = "output_tokens"\nexpiring = true\n'
        '[[providers.opencode.windows]]\nname = "5h"\nlength_s = 18000\nbudget = 100000\n')
    monkeypatch.setenv("LANECTL_HOME", str(tmp_path))
    log = EventLog(tmp_path / "state" / "events.jsonl")

    args = SimpleNamespace(record=False, execute=False, lane="implement")

    assert burn._cmd(args, log) == 0
    out = capsys.readouterr().out
    assert "no burn plan" in out and "placeholder" in out
