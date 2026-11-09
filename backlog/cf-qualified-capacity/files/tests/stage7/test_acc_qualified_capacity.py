"""Acceptance: source-qualified capacity (planner-owned)."""
from datetime import datetime, timezone

from lanectl import capacity, probe, windows
from lanectl.contracts import make_event

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)      # 5h window 10:00-15:00 UTC
RAW = {"revision": 5, "providers": {"opencode": {
    "unit": "output_tokens", "expiring": True, "pool": "opencode-go:default", "freshness_s": 3600,
    "windows": [{"name": "5h", "length_s": 18000, "budget": 1000000}],
    "estimates": {"S": 15000}}}}


def _policy(**over):
    raw = {**RAW, "providers": {"opencode": {**RAW["providers"]["opencode"], **over}}}
    return capacity.AllocationPolicy.from_dict(raw)


def _usage(ts, n):
    return make_event("usage.recorded", {"provider": "opencode", "source": "adapter",
                                         "units": {"output_tokens": n}}, ts=ts)


def _observed(observed_at, value, window_start="2026-11-09T00:00:00Z"):
    return make_event("capacity.observed", {
        "provider": "opencode", "pool": "opencode-go:default", "source": "opencode-stats",
        "unit": "output_tokens", "basis": "measured", "observed_at": observed_at, "value": value,
        "value_kind": "cumulative", "window_start": window_start, "scope": "host"}, ts=observed_at)


def test_policy_pool_and_freshness_defaults():
    p = _policy()
    assert p.providers["opencode"].pool == "opencode-go:default" and p.providers["opencode"].freshness_s == 3600
    raw = {"revision": 1, "providers": {"x": {"unit": "requests", "windows": []}}}
    q = capacity.AllocationPolicy.from_dict(raw).providers["x"]
    assert q.pool == "x:default" and q.freshness_s is None


def test_unknown_is_not_zero():
    v = capacity.qualified([_usage("2026-11-09T11:00:00Z", 5000)], _policy(), NOW)["opencode"]
    assert v["basis"] == "unknown" and v["outside_lane"] is None and v["lane_used"] == 5000
    a = capacity.capacity_admission([], _policy(), NOW, "opencode", "S")
    assert a["decision"] == "admit" and a["burnable"] is None and a["basis"] == "unknown"
    assert any("capacity unknown" in r for r in a["reasons"])


def test_fresh_observation_measures_outside_lane_spend():
    ev = [_usage("2026-11-09T08:00:00Z", 30000), _usage("2026-11-09T11:00:00Z", 10000),
          _observed("2026-11-09T11:30:00Z", 100000)]
    v = capacity.qualified(ev, _policy(), NOW)["opencode"]
    assert v["basis"] == "measured" and not v["stale"] and v["pool"] == "opencode-go:default"
    assert v["outside_lane"] == 60000 and v["lane_used"] == 10000
    a = capacity.capacity_admission(ev, _policy(), NOW, "opencode", "S")
    assert a["basis"] == "measured" and a["burnable"] == 1000000 - 10000 - 60000 and a["decision"] == "admit"


def test_stale_observation_becomes_unknown():
    ev = [_observed("2026-11-09T10:30:00Z", 100000)]
    v = capacity.qualified(ev, _policy(), NOW)["opencode"]
    assert v["basis"] == "unknown" and v["stale"] is True and v["outside_lane"] is None


def test_denial_blocks_until_reset():
    deny = make_event("capacity.observed", {
        "provider": "opencode", "pool": "opencode-go:default", "source": "window-detector",
        "unit": "output_tokens", "basis": "measured", "observed_at": "2026-11-09T11:00:00Z",
        "value": None, "value_kind": "denial", "reset_at": "2026-11-09T13:00:00Z"}, ts="2026-11-09T11:00:00Z")
    ev = [_observed("2026-11-09T11:30:00Z", 100000), deny]
    assert capacity.qualified(ev, _policy(), NOW)["opencode"]["denied"] is True
    a = capacity.capacity_admission(ev, _policy(), NOW, "opencode", "S")
    assert a["decision"] == "block" and a["burnable"] == 0 and any("denial" in r for r in a["reasons"])
    later = datetime(2026, 11, 9, 14, 0, tzinfo=timezone.utc)
    assert capacity.qualified(ev, _policy(), later)["opencode"]["denied"] is False


def test_probe_and_detector_observations():
    payload = {"provider": "opencode", "window": "day", "observed": {
        "source": "opencode-stats", "range_from": "2026-11-09T00:00:00Z", "range_to": "2026-11-09T11:30:00Z",
        "output_tokens": 100000, "input_tokens": 1, "reasoning_tokens": 1, "cache_read_tokens": 1, "sessions": 2}}
    d = probe.capacity_observation(payload, _policy())
    assert d["pool"] == "opencode-go:default" and d["basis"] == "measured" and d["value"] == 100000
    assert d["value_kind"] == "cumulative" and d["scope"] == "host" and d["fresh_until"] == "2026-11-09T12:30:00Z"
    make_event("capacity.observed", d)
    hit = {"provider": "opencode", "window": "5h", "observed": {
        "attempt_id": "it-a1", "exhausted_at": "2026-11-09T11:00:00Z", "reset_at": "2026-11-09T13:00:00Z"}}
    w = windows.capacity_observation(hit, _policy())
    assert w["value_kind"] == "denial" and w["value"] is None and w["reset_at"] == "2026-11-09T13:00:00Z"
    make_event("capacity.observed", w)
