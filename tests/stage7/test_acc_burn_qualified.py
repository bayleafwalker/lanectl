"""Acceptance: qualified burn, revalidation, allocation decisions and dwell (planner-owned)."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from lanectl import burn
from lanectl.contracts import make_event
from lanectl.events import EventLog

NOW = datetime(2026, 11, 9, 14, 30, tzinfo=timezone.utc)        # 5h window 10:00-15:00, ends in 30 min
CAPS = {"concurrency": 3, "items_per_day": 48, "accepted_unlanded_max": 8}
READY = [("aa", "S"), ("bb", "S")]


def _raw(basis="verified"):
    return {"revision": 7, "burn": {"start_within_s": 3600, "min_burnable": 10000},
            "allocation": {"min_dwell_s": 1800, "change_threshold": 0.2},
            "providers": {"opencode": {"unit": "output_tokens", "expiring": True, "pool": "p:1",
                                       "freshness_s": 3600, "estimates": {"S": 15000},
                                       "windows": [{"name": "5h", "length_s": 18000, "budget": 100000,
                                                    "budget_basis": basis}]}}}


def _obs(value=10000, at="2026-11-09T14:20:00Z"):
    return make_event("capacity.observed", {"provider": "opencode", "pool": "p:1", "source": "opencode-stats",
                      "unit": "output_tokens", "basis": "measured", "observed_at": at, "value": value,
                      "value_kind": "cumulative", "window_start": "2026-11-09T00:00:00Z"}, ts=at)


def _deny():
    return make_event("capacity.observed", {"provider": "opencode", "pool": "p:1", "source": "window-detector",
                      "unit": "output_tokens", "basis": "measured", "observed_at": "2026-11-09T14:25:00Z",
                      "value": None, "value_kind": "denial", "reset_at": "2026-11-09T15:00:00Z"},
                      ts="2026-11-09T14:25:00Z")


def test_placeholder_budget_never_burns():
    assert any("placeholder" in r for r in burn.check([_obs()], _raw("placeholder"), NOW))
    assert burn.plan_burn([_obs()], _raw("placeholder"), NOW, READY, CAPS, 0, 0) is None


def test_unknown_capacity_never_burns():
    assert any("unknown" in r for r in burn.check([], _raw(), NOW))
    assert burn.plan_burn([], _raw(), NOW, READY, CAPS, 0, 0) is None


def test_measured_verified_capacity_plans():
    assert burn.check([_obs()], _raw(), NOW) == []
    p = burn.plan_burn([_obs()], _raw(), NOW, READY, CAPS, 0, 0)
    assert p["burnable"] == 90000 and p["items"] == ["aa", "bb"]


def _decisions(log, **m):
    return [e["data"] for e in log.read() if e["type"] == "lane.decision"
            and all(e["data"].get(k) == v for k, v in m.items())]


def test_execute_records_and_correlates(tmp_path):
    log = EventLog(tmp_path / "e.jsonl")
    log.append("capacity.observed", _obs()["data"])
    plan = burn.plan_burn(log.read(), _raw(), NOW, READY, CAPS, 0, 0)
    claims = burn.execute_plan(log, plan, _raw(), NOW, lambda rid: SimpleNamespace(attempt_id=f"{rid}-a1"))
    assert [c.attempt_id for c in claims] == ["aa-a1", "bb-a1"]
    prop = _decisions(log, kind="allocation", phase="proposed")
    assert len(prop) == 1 and prop[0]["items"] == ["aa", "bb"] and prop[0]["mechanism"] == "burn-plan/v1"
    appl = _decisions(log, kind="allocation", phase="applied")
    assert [a["subject"] for a in appl] == [{"item_id": "aa", "attempt_id": "aa-a1"},
                                            {"item_id": "bb", "attempt_id": "bb-a1"}]
    assert all(a["proposal_id"] == prop[0]["decision_id"] for a in appl)


def test_execute_revalidates_and_refuses_on_denial(tmp_path):
    log = EventLog(tmp_path / "e.jsonl")
    log.append("capacity.observed", _obs()["data"])
    plan = burn.plan_burn(log.read(), _raw(), NOW, READY, CAPS, 0, 0)
    log.append("capacity.observed", _deny()["data"])        # the pool is denied before the plan applies
    called = []
    claims = burn.execute_plan(log, plan, _raw(), NOW, lambda rid: called.append(rid))
    assert claims == [] and called == []
    ref = _decisions(log, kind="allocation", phase="refused")
    assert len(ref) == 1 and any("denied" in r for r in ref[0]["reasons"])


def test_dwell_and_denial_override():
    applied = make_event("lane.decision", {"decision_id": "dec-1", "kind": "allocation", "phase": "applied",
                         "chosen": "aa", "mechanism": "burn-plan/v1", "policy_revision": "allocation@7",
                         "burnable": 88000}, ts=(NOW - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    reasons = burn.check([_obs(), applied], _raw(), NOW)
    assert any("dwell" in r for r in reasons)
    assert burn.plan_burn([_obs(), applied], _raw(), NOW, READY, CAPS, 0, 0) is None
    assert any("denied" in r for r in burn.check([_obs(), applied, _deny()], _raw(), NOW))
