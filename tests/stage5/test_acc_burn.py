"""Acceptance: burn-down planning (planner-owned)."""
from datetime import datetime, timedelta, timezone

from lanectl.burn import plan_burn
from lanectl.contracts import make_event

T0 = datetime(2026, 11, 8, 10, 0, tzinfo=timezone.utc)
POLICY = {"revision": 4, "burn": {"start_within_s": 3600, "min_burnable": 10000},
          "providers": {"opencode": {"unit": "output_tokens", "expiring": True, "reservations": {},
                                     "windows": [{"name": "5h", "length_s": 18000, "budget": 100000,
                                                  "anchor": "2026-11-08T10:00:00Z"}],
                                     "estimates": {"S": 15000, "M": 40000, "L": 100000}}}}
CAPS = {"concurrency": 3, "items_per_day": 48, "accepted_unlanded_max": 8}
READY = [("aa", "M"), ("bb", "M"), ("cc", "S"), ("dd", "S")]


def _used(n):
    e = make_event("usage.recorded", {"provider": "opencode", "source": "adapter", "units": {"output_tokens": n}})
    e["ts"] = "2026-11-08T11:00:00Z"
    return e


def test_no_burn_before_the_last_hour():
    assert plan_burn([], POLICY, T0 + timedelta(hours=2), READY, CAPS, 0, 0) is None


def test_burn_fills_burnable_in_backlog_order():
    p = plan_burn([_used(10000)], POLICY, T0 + timedelta(hours=4, minutes=30), READY, CAPS, 0, 0)
    assert p["provider"] == "opencode" and p["window"] == "5h" and p["burnable"] == 90000
    assert p["items"] == ["aa", "bb"]          # 40000 + 40000; cc would exceed 90000 at 95000


def test_slots_bound_the_plan():
    p = plan_burn([], POLICY, T0 + timedelta(hours=4, minutes=30), READY, CAPS, running=2, unlanded=0)
    assert p["items"] == ["aa"]
    assert plan_burn([], POLICY, T0 + timedelta(hours=4, minutes=30), READY, CAPS, 0, unlanded=8) is None


def test_small_leftover_is_ignored():
    assert plan_burn([_used(95000)], POLICY, T0 + timedelta(hours=4, minutes=30), READY, CAPS, 0, 0) is None
