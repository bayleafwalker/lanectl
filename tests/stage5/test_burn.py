"""Unit coverage for burn-down planning and its command plugin."""
from datetime import datetime, timedelta, timezone

from lanectl.burn import plan_burn
from lanectl.cli import discover_plugins
from lanectl.contracts import make_event

T0 = datetime(2026, 11, 8, 10, 0, tzinfo=timezone.utc)
CAPS = {"concurrency": 3, "items_per_day": 48, "accepted_unlanded_max": 8}
POLICY = {
    "revision": 4,
    "burn": {"start_within_s": 3600, "min_burnable": 10000},
    "providers": {"opencode": {
        "unit": "output_tokens", "expiring": True, "reservations": {},
        "windows": [{"name": "5h", "length_s": 18000, "budget": 100000,
                     "anchor": "2026-11-08T10:00:00Z"}],
        "estimates": {"S": 15000, "M": 40000, "L": 100000},
    }},
}
LAST_HALF_HOUR = T0 + timedelta(hours=4, minutes=30)


def _used(n, at="2026-11-08T11:00:00Z"):
    e = make_event("usage.recorded",
                   {"provider": "opencode", "source": "adapter",
                    "units": {"output_tokens": n}})
    e["ts"] = at
    return e


def _provider_policy(**overrides):
    policy = {k: v for k, v in POLICY.items() if k != "providers"}
    policy["providers"] = {"opencode": dict(POLICY["providers"]["opencode"], **overrides)}
    return policy


def test_plan_reports_the_qualifying_window_and_reasons():
    plan = plan_burn([], POLICY, LAST_HALF_HOUR, [("aa", "M")], CAPS, 0, 0)
    assert plan is not None
    assert (plan["provider"], plan["window"], plan["burnable"]) == ("opencode", "5h", 100000)
    assert plan["items"] == ["aa"]
    assert any("ends in" in r for r in plan["reasons"])


def test_start_within_boundary_is_inclusive():
    # Window ends at 15:00; at 14:00 exactly one hour remains.
    plan = plan_burn([], POLICY, T0 + timedelta(hours=4), [("aa", "M")], CAPS, 0, 0)
    assert plan is not None and plan["items"] == ["aa"]


def test_min_burnable_boundary_requires_something_that_fits():
    tight = plan_burn([_used(85000)], POLICY, LAST_HALF_HOUR, [("aa", "S")], CAPS, 0, 0)
    assert tight is not None and tight["items"] == ["aa"]      # exactly 15000 burnable
    below = plan_burn([_used(90000)], POLICY, LAST_HALF_HOUR, [("aa", "S")], CAPS, 0, 0)
    assert below is None                                      # 10000 left, item needs 15000


def test_slots_use_the_tighter_of_concurrency_and_unlanded():
    caps = {"concurrency": 5, "items_per_day": 48, "accepted_unlanded_max": 2}
    plan = plan_burn([], POLICY, LAST_HALF_HOUR,
                     [("aa", "S"), ("bb", "S"), ("cc", "S")], caps, running=0, unlanded=1)
    assert plan is not None and plan["items"] == ["aa"]       # unlanded leaves one slot


def test_non_expiring_provider_never_plans():
    policy = _provider_policy(expiring=False)
    assert plan_burn([], policy, LAST_HALF_HOUR, [("aa", "M")], CAPS, 0, 0) is None


def test_missing_burn_rules_never_plans():
    policy = {k: v for k, v in POLICY.items() if k != "burn"}
    assert plan_burn([], policy, LAST_HALF_HOUR, [("aa", "M")], CAPS, 0, 0) is None


def test_burn_is_registered_as_a_command_plugin():
    modules = discover_plugins("lanectl")
    assert "burn" in {module.__name__.rsplit(".", 1)[-1] for module in modules}
