"""Acceptance: burn uses capacity's window bounds and the tightest window (planner-owned)."""
from datetime import datetime, timezone

from lanectl import burn
from lanectl.capacity import AllocationPolicy, project
from lanectl.contracts import make_event

CAPS = {"concurrency": 3, "items_per_day": 48, "accepted_unlanded_max": 8}
READY = [("aa", "S"), ("bb", "S"), ("cc", "S")]
FIVE_H = {"name": "5h", "length_s": 18000, "budget": 100000, "budget_basis": "verified"}


def _raw(*windows):
    return {"revision": 8, "burn": {"start_within_s": 3600, "min_burnable": 10000},
            "allocation": {"min_dwell_s": 1800, "change_threshold": 0.2},
            "providers": {"opencode": {"unit": "output_tokens", "expiring": True, "pool": "p:1",
                                       "freshness_s": 3600, "estimates": {"S": 15000},
                                       "windows": list(windows)}}}


def _week(budget):
    return {"name": "week", "length_s": 604800, "budget": budget, "budget_basis": "verified"}


def _use(n, ts, aid):
    return make_event("usage.recorded", {"provider": "opencode", "source": "adapter", "attempt_id": aid,
                                         "model": "m", "units": {"output_tokens": n}}, ts=ts)


def _obs(at, value=10000):
    return make_event("capacity.observed", {"provider": "opencode", "pool": "p:1", "source": "opencode-stats",
                      "unit": "output_tokens", "basis": "measured", "observed_at": at, "value": value,
                      "value_kind": "cumulative", "window_start": "2026-11-09T00:00:00Z"}, ts=at)


# Epoch-grid 5h window on 2026-11-09 is 11:00-16:00; the epoch week is 2026-11-05..2026-11-12.
LATE = datetime(2026, 11, 9, 15, 30, tzinfo=timezone.utc)
EVENTS = [_use(45000, "2026-11-06T12:00:00Z", "xx-a1"), _use(10000, "2026-11-09T11:30:00Z", "yy-a1"),
          _obs("2026-11-09T15:20:00Z")]


def test_exhausted_week_blocks_a_5h_burn():
    assert burn.plan_burn(EVENTS, _raw(FIVE_H, _week(50000)), LATE, READY, CAPS, 0, 0) is None


def test_burnable_is_the_tightest_window():
    p = burn.plan_burn(EVENTS, _raw(FIVE_H, _week(1_000_000)), LATE, READY, CAPS, 0, 0)
    assert p is not None and p["burnable"] == 90000 and p["items"] == ["aa", "bb", "cc"]


def test_week_tighter_than_5h_caps_items():
    p = burn.plan_burn(EVENTS, _raw(FIVE_H, _week(95000)), LATE, READY, CAPS, 0, 0)
    assert p is not None and p["burnable"] == 40000 and p["items"] == ["aa", "bb"]


def test_burn_window_matches_capacity_projection():
    early = datetime(2026, 11, 9, 14, 30, tzinfo=timezone.utc)
    events = [_use(10000, "2026-11-09T11:30:00Z", "yy-a1"), _obs("2026-11-09T14:20:00Z")]
    raw = _raw(FIVE_H)
    end = project(events, AllocationPolicy.from_dict(raw), early)["opencode"]["5h"]["window_end"]
    assert end == "2026-11-09T16:00:00Z"
    assert burn.plan_burn(events, raw, early, READY, CAPS, 0, 0) is None   # 90 min left, not within 1h
