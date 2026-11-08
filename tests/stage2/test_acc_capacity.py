"""Acceptance: capacity ledger and allocation projection semantics (planner-owned).

Windows are fixed-length and aligned to an anchor (policy anchor, or the latest
window.observed reset_at). Interactive reservations decay linearly toward the
window end; expiring capacity above the decayed reservation is burnable.
"""
from datetime import datetime, timedelta, timezone

from hypothesis import given, strategies as st

from lanectl.capacity import AllocationPolicy, project
from lanectl.contracts import make_event

T0 = datetime(2026, 11, 8, 10, 0, tzinfo=timezone.utc)
POLICY = AllocationPolicy.from_dict({
    "revision": 1,
    "providers": {
        "opencode-go": {"unit": "output_tokens", "expiring": True,
                        "windows": [{"name": "5h", "length_s": 18000, "budget": 1000,
                                     "anchor": "2026-11-08T10:00:00Z"}],
                        "reservations": {"interactive": 0.4}},
        "api": {"unit": "cost_usd", "expiring": False,
                "windows": [{"name": "day", "length_s": 86400, "budget": 5,
                             "anchor": "2026-11-08T00:00:00Z"}],
                "reservations": {}},
    }})


def usage(provider, n, at, source="adapter", unit="output_tokens"):
    ev = make_event("usage.recorded", {"provider": provider, "source": source, "units": {unit: n}})
    ev["ts"] = at.strftime("%Y-%m-%dT%H:%M:%SZ")
    return ev


def test_empty_window():
    w = project([], POLICY, now=T0)["opencode-go"]["5h"]
    assert (w["used"], w["remaining"], w["reserved_effective"], w["burnable"]) == (0, 1000, 400.0, 600.0)
    assert w["window_start"] == "2026-11-08T10:00:00Z" and w["window_end"] == "2026-11-08T15:00:00Z"


def test_half_window_with_lane_and_interactive_usage():
    ev = [usage("opencode-go", 300, T0 + timedelta(hours=1)),
          usage("opencode-go", 100, T0 + timedelta(hours=2), source="claude-code-interactive"),
          usage("opencode-go", 999, T0 - timedelta(hours=1))]           # previous window
    w = project(ev, POLICY, now=T0 + timedelta(hours=2, minutes=30))["opencode-go"]["5h"]
    assert w["used"] == 400 and w["remaining"] == 600
    assert w["reserved_effective"] == 150.0          # (400 - 100) * 0.5 time left
    assert w["burnable"] == 450.0


def test_next_window_is_aligned_to_anchor():
    w = project([], POLICY, now=T0 + timedelta(hours=6))["opencode-go"]["5h"]
    assert w["window_start"] == "2026-11-08T15:00:00Z"


def test_observed_reset_overrides_anchor():
    obs = make_event("window.observed", {"provider": "opencode-go", "window": "5h",
                                         "observed": {"reset_at": "2026-11-08T13:00:00Z"}})
    obs["ts"] = "2026-11-08T11:00:00Z"
    w = project([obs], POLICY, now=T0 + timedelta(hours=1))["opencode-go"]["5h"]
    assert (w["window_start"], w["window_end"]) == ("2026-11-08T08:00:00Z", "2026-11-08T13:00:00Z")


def test_non_expiring_capacity_is_never_burnable():
    w = project([usage("api", 1, T0, unit="cost_usd")], POLICY, now=T0)["api"]["day"]
    assert w["remaining"] == 4 and w["burnable"] == 0 and w["burn_down_allowed"] is False


@given(st.lists(st.tuples(st.integers(0, 17999), st.integers(0, 400), st.booleans()), max_size=20),
       st.integers(0, 17999), st.integers(0, 17999))
def test_burnable_is_bounded_and_grows_as_reservation_decays(rows, t1, t2):
    ev = [usage("opencode-go", n, T0 + timedelta(seconds=s),
                source="claude-code-interactive" if inter else "adapter") for s, n, inter in rows]
    a, b = sorted((t1, t2))
    upto = [e for e, (s, _, _) in zip(ev, rows) if s <= a]
    wa = project(upto, POLICY, now=T0 + timedelta(seconds=a))["opencode-go"]["5h"]
    wb = project(upto, POLICY, now=T0 + timedelta(seconds=b))["opencode-go"]["5h"]
    for w in (wa, wb):
        assert 0 <= w["burnable"] <= max(w["remaining"], 0)
    assert wb["burnable"] >= wa["burnable"]          # no new usage: decay only frees capacity
