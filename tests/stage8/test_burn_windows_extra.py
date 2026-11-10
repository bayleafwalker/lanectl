"""Burn follows capacity's window bounds and spends only the tightest window.

Companion coverage for the planner acceptance file: the burn window is exactly
the one ``capacity.project`` reports (epoch grid, policy anchor or observed
reset), and its amount is the minimum headroom across every window of the
provider rather than the largest per-window usage subtracted from all of them.
"""
from datetime import datetime, timezone

from lanectl import burn
from lanectl.capacity import AllocationPolicy, project
from lanectl.contracts import make_event

CAPS = {"concurrency": 3, "items_per_day": 48, "accepted_unlanded_max": 8}
READY = [("aa", "S"), ("bb", "S"), ("cc", "S")]
FIVE_H = {"name": "5h", "length_s": 18000, "budget": 100000, "budget_basis": "verified"}


def _week(budget):
    return {"name": "week", "length_s": 604800, "budget": budget, "budget_basis": "verified"}


def _raw(*windows):
    return {"revision": 8, "burn": {"start_within_s": 3600, "min_burnable": 10000},
            "allocation": {"min_dwell_s": 1800, "change_threshold": 0.2},
            "providers": {"opencode": {"unit": "output_tokens", "expiring": True, "pool": "p:1",
                                       "freshness_s": 3600, "estimates": {"S": 15000},
                                       "windows": list(windows)}}}


def _use(n, ts, aid):
    return make_event("usage.recorded", {
        "provider": "opencode", "source": "adapter", "attempt_id": aid,
        "model": "m", "units": {"output_tokens": n}}, ts=ts)


def _obs(at, value, start):
    return make_event("capacity.observed", {
        "provider": "opencode", "pool": "p:1", "source": "opencode-stats",
        "unit": "output_tokens", "basis": "measured", "observed_at": at, "value": value,
        "value_kind": "cumulative", "window_start": start}, ts=at)


def _applied(burnable, ts):
    return make_event("lane.decision", {
        "decision_id": "dec-1", "kind": "allocation", "phase": "applied",
        "chosen": "aa", "mechanism": "burn-plan/v1",
        "policy_revision": "allocation@8", "burnable": burnable}, ts=ts)


def _end(events, raw, now):
    """The bounds capacity reports for the provider's only/shortest window."""
    return project(events, AllocationPolicy.from_dict(raw), now)["opencode"]


def test_week_window_follows_capacity_not_the_observation_start():
    # The latest observation starts 2026-11-09, but the unanchored weekly window
    # is on the epoch grid and ends 2026-11-12T00:00 (30 min after ``now``).
    raw = _raw(_week(1_000_000))
    now = datetime(2026, 11, 11, 23, 30, tzinfo=timezone.utc)
    events = [_use(10000, "2026-11-11T22:00:00Z", "aa-a1"),
              _obs("2026-11-11T23:20:00Z", 10000, "2026-11-09T00:00:00Z")]
    assert _end(events, raw, now)["week"]["window_end"] == "2026-11-12T00:00:00Z"

    plan = burn.plan_burn(events, raw, now, READY, CAPS, 0, 0)
    assert plan is not None and plan["window"] == "week"
    assert plan["burnable"] == 990000 and plan["items"] == ["aa", "bb", "cc"]

    # Two hours before that same capacity boundary nothing is due yet.
    earlier = datetime(2026, 11, 11, 22, 0, tzinfo=timezone.utc)
    early_events = [_use(10000, "2026-11-11T20:00:00Z", "aa-a1"),
                    _obs("2026-11-11T21:50:00Z", 10000, "2026-11-09T00:00:00Z")]
    assert _end(early_events, raw, earlier)["week"]["window_end"] == "2026-11-12T00:00:00Z"
    assert burn.plan_burn(early_events, raw, earlier, READY, CAPS, 0, 0) is None


def test_a_tight_non_ending_window_limits_an_ending_5h_window():
    # The 5h window ends first and is nearly empty, but the weekly window it sits
    # in has only 5000 left: the plan is capped by that minimum, not by the 5h
    # window's own headroom.  The explicit 5h anchor isolates the per-window
    # arithmetic from a disagreement over bounds.
    raw = _raw(dict(FIVE_H, anchor="2026-11-09T11:00:00Z"), _week(60000))
    now = datetime(2026, 11, 9, 15, 30, tzinfo=timezone.utc)
    events = [_use(45000, "2026-11-06T12:00:00Z", "xx-a1"),
              _use(10000, "2026-11-09T11:30:00Z", "yy-a1"),
              _obs("2026-11-09T15:20:00Z", 10000, "2026-11-09T00:00:00Z")]
    views = _end(events, raw, now)
    assert (views["5h"]["window_end"], views["week"]["remaining"]) == \
        ("2026-11-09T16:00:00Z", 5000)
    assert burn.plan_burn(events, raw, now, READY, CAPS, 0, 0) is None


def test_dwell_compares_against_the_tightest_window():
    # Recorded burnable 9000 sits within 20% of the weekly window's 10000 but far
    # from the empty 5h window's headroom, so the per-window minimum holds dwell.
    raw = _raw(FIVE_H, _week(50000))
    now = datetime(2026, 11, 9, 15, 30, tzinfo=timezone.utc)
    events = [_use(40000, "2026-11-06T12:00:00Z", "xx-a1"),
              _obs("2026-11-09T15:20:00Z", 40000, "2026-11-05T00:00:00Z"),
              _applied(9000, "2026-11-09T15:20:00Z")]
    views = _end(events, raw, now)
    assert views["5h"]["remaining"] == 100000 and views["week"]["remaining"] == 10000
    reasons = burn.check(events, raw, now)
    assert any("dwell" in reason for reason in reasons)
    assert burn.plan_burn(events, raw, now, READY, CAPS, 0, 0) is None
