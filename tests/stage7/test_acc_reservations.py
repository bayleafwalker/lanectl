"""Acceptance: capacity reservations and usage dedup (planner-owned)."""
import os
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lanectl import capacity, runner
from lanectl.adapters import AdapterResult
from lanectl.contracts import make_event
from lanectl.reap import reap
from tests.seed.test_end_to_end import SUB_TEST  # estate comes from tests/stage7/conftest.py

LATER = datetime.now(timezone.utc) + timedelta(days=1)


def _policy_home():
    gov = Path(os.environ["LANECTL_HOME"]) / "governance"
    (gov / "allocation.toml").write_text(textwrap.dedent("""
        revision = 9
        [providers.scripted]
        unit = "output_tokens"
        expiring = true
        pool = "scripted:test"
        [[providers.scripted.windows]]
        name = "5h"
        length_s = 18000
        budget = 1000000
        [providers.scripted.estimates]
        S = 15000
        """))


def good_with_usage(n):
    def fn(*, worktree, **_):
        wt = Path(worktree)
        (wt / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
        (wt / "tests" / "test_sub_extra.py").write_text("from calc import sub\n\ndef test_neg():\n    assert sub(1, 2) == -1\n")
        return AdapterResult("done", 0, "ok", None, {"output_tokens": n})
    return fn


def _of(log, etype):
    return [e["data"] for e in log.read() if e["type"] == etype]


def test_reserve_on_claim_reconcile_on_completion(estate):
    repo, release, log = estate
    _policy_home()
    release("add-sub", SUB_TEST)
    c = runner.admit("implement", log)
    res = _of(log, "capacity.reserved")
    assert len(res) == 1 and res[0]["reservation_id"] == f"res-{c.attempt_id}"
    assert res[0]["amount"] == 15000 and res[0]["pool"] == "scripted:test" and res[0]["unit"] == "output_tokens"
    pol = capacity.AllocationPolicy.load()
    assert capacity.in_flight(log.read(), "scripted", "scripted:test") == 15000
    runner.execute(c, log, adapter_fn=good_with_usage(12345))
    rec = _of(log, "capacity.reconciled")
    assert rec == [{"reservation_id": f"res-{c.attempt_id}", "actual": 12345, "outcome": "completed"}]
    assert capacity.in_flight(log.read(), "scripted", "scripted:test") == 0
    assert pol.providers["scripted"].pool == "scripted:test"


def test_reap_reconciles_abandoned_reservation(estate):
    repo, release, log = estate
    _policy_home()
    release("add-sub", SUB_TEST)
    c = runner.admit("implement", log)
    assert reap(log, now=LATER, older_than_s=60, max_attempts=2) == [c.attempt_id]
    rec = _of(log, "capacity.reconciled")
    assert rec == [{"reservation_id": f"res-{c.attempt_id}", "actual": None, "outcome": "recovered"}]
    assert reap(log, now=LATER, older_than_s=60, max_attempts=2) == []
    assert len(_of(log, "capacity.reconciled")) == 1


def test_no_policy_no_reservation(estate):
    repo, release, log = estate
    release("add-sub", SUB_TEST)
    runner.admit("implement", log)
    assert _of(log, "capacity.reserved") == []


def _pol():
    return capacity.AllocationPolicy.from_dict({"revision": 1, "providers": {"opencode": {
        "unit": "output_tokens", "expiring": True, "pool": "p:1", "freshness_s": 3600,
        "windows": [{"name": "5h", "length_s": 18000, "budget": 100000}], "estimates": {"S": 1000}}}})


NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


def test_in_flight_reduces_measured_burnable_and_usage_dedups():
    obs = make_event("capacity.observed", {"provider": "opencode", "pool": "p:1", "source": "opencode-stats",
                     "unit": "output_tokens", "basis": "measured", "observed_at": "2026-11-09T11:30:00Z",
                     "value": 20000, "value_kind": "cumulative", "window_start": "2026-11-09T00:00:00Z"},
                     ts="2026-11-09T11:30:00Z")
    u1 = make_event("usage.recorded", {"provider": "opencode", "source": "adapter", "attempt_id": "aa-a1",
                    "units": {"output_tokens": 5000}}, ts="2026-11-09T11:00:00Z")
    u2 = make_event("usage.recorded", {"provider": "opencode", "source": "hook", "attempt_id": "aa-a1",
                    "units": {"output_tokens": 5000}}, ts="2026-11-09T11:01:00Z")
    rsv = make_event("capacity.reserved", {"reservation_id": "res-bb-a1", "provider": "opencode", "pool": "p:1",
                     "unit": "output_tokens", "amount": 7000, "attempt_id": "bb-a1"}, ts="2026-11-09T11:40:00Z")
    ev = [u1, u2, obs, rsv]
    v = capacity.qualified(ev, _pol(), NOW)["opencode"]
    assert v["lane_used"] == 5000 and v["outside_lane"] == 15000 and v["in_flight"] == 7000
    a = capacity.capacity_admission(ev, _pol(), NOW, "opencode", "S")
    assert a["burnable"] == 100000 - 5000 - 15000 - 7000
