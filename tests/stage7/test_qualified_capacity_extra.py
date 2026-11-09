"""Source-qualified capacity: extra edges beyond the planner acceptance file."""
import json
from datetime import datetime, timezone

from lanectl import capacity, cli, probe, windows
from lanectl.contracts import make_event
from lanectl.events import EventLog

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
RAW = {"revision": 5, "providers": {"opencode": {
    "unit": "output_tokens", "expiring": True, "pool": "opencode-go:default", "freshness_s": 3600,
    "windows": [{"name": "5h", "length_s": 18000, "budget": 1000000}],
    "estimates": {"S": 15000}}}}


def _policy(**over):
    spec = {**RAW["providers"]["opencode"], **over}
    return capacity.AllocationPolicy.from_dict({"revision": 5, "providers": {"opencode": spec}})


def _usage(ts, n):
    return make_event("usage.recorded", {"provider": "opencode", "source": "adapter",
                                         "units": {"output_tokens": n}}, ts=ts)


def _observed(observed_at, value, window_start="2026-11-09T00:00:00Z"):
    return make_event("capacity.observed", {
        "provider": "opencode", "pool": "opencode-go:default", "source": "opencode-stats",
        "unit": "output_tokens", "basis": "measured", "observed_at": observed_at, "value": value,
        "value_kind": "cumulative", "window_start": window_start, "scope": "host"}, ts=observed_at)


def _denial(observed_at, reset_at):
    return make_event("capacity.observed", {
        "provider": "opencode", "pool": "opencode-go:default", "source": "window-detector",
        "unit": "output_tokens", "basis": "measured", "observed_at": observed_at,
        "value": None, "value_kind": "denial", "reset_at": reset_at}, ts=observed_at)


def test_outside_lane_spend_never_goes_negative():
    ev = [_usage("2026-11-09T09:00:00Z", 120000), _observed("2026-11-09T11:30:00Z", 100000)]
    assert capacity.qualified(ev, _policy(), NOW)["opencode"]["outside_lane"] == 0


def test_freshness_boundary_and_missing_observation():
    # Exactly at the deadline is still fresh; one second later is stale.
    at_deadline = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
    ev = [_observed("2026-11-09T11:00:00Z", 100000)]
    assert capacity.qualified(ev, _policy(), at_deadline)["opencode"]["stale"] is False
    after = datetime(2026, 11, 9, 12, 0, 1, tzinfo=timezone.utc)
    assert capacity.qualified(ev, _policy(), after)["opencode"]["stale"] is True
    missing = capacity.qualified([], _policy(), NOW)["opencode"]
    assert missing["stale"] is False and missing["observed_at"] is None


def test_measured_burnable_subtracts_effective_reservation():
    ev = [_observed("2026-11-09T11:30:00Z", 100000)]
    # 4h of the current 11:00-16:00 window remain: 0.8 * 0.2 * 1_000_000 is
    # reserved, and the 100000-token snapshot is outside-lane spend.
    a = capacity.capacity_admission(ev, _policy(reservations={"interactive": 0.2}),
                                    NOW, "opencode", "S")
    assert a["basis"] == "measured"
    assert a["burnable"] == 1000000 - 0 - 100000 - 160000


def test_denial_without_reset_blocks_for_the_whole_window():
    ev = [_denial("2026-11-09T11:05:00Z", None)]
    assert capacity.qualified(ev, _policy(), NOW)["opencode"]["denied"] is True
    a = capacity.capacity_admission(ev, _policy(), NOW, "opencode", "S")
    assert a["decision"] == "block" and a["burnable"] == 0
    # A denial observed before this window does not block it.
    early = [_denial("2026-11-09T09:00:00Z", None)]
    assert capacity.qualified(early, _policy(), NOW)["opencode"]["denied"] is False


def test_observation_for_another_pool_is_ignored():
    other = make_event("capacity.observed", {
        "provider": "opencode", "pool": "someone-else:default", "source": "opencode-stats",
        "unit": "output_tokens", "basis": "measured", "observed_at": "2026-11-09T11:30:00Z",
        "value": 1, "value_kind": "cumulative", "window_start": "2026-11-09T00:00:00Z"},
        ts="2026-11-09T11:30:00Z")
    assert capacity.qualified([other], _policy(), NOW)["opencode"]["basis"] == "unknown"


def test_unqualified_policy_keeps_the_ledger_projection():
    legacy = capacity.AllocationPolicy.from_dict({"revision": 3, "providers": {"p": {
        "unit": "output_tokens", "expiring": True,
        "windows": [{"name": "5h", "length_s": 18000, "budget": 50000}],
        "estimates": {"S": 1}}}})
    a = capacity.capacity_admission([], legacy, NOW, "p", "S")
    assert a["decision"] == "admit" and a["burnable"] == 50000 and a["basis"] == "measured"


def test_probe_observation_omits_fresh_until_without_freshness():
    raw = {"revision": 1, "providers": {"opencode": {"unit": "output_tokens", "windows": []}}}
    policy = capacity.AllocationPolicy.from_dict(raw)
    payload = {"provider": "opencode", "observed": {
        "range_from": "2026-11-09T00:00:00Z", "range_to": "2026-11-09T11:30:00Z",
        "output_tokens": 7}}
    row = probe.capacity_observation(payload, policy)
    assert row["pool"] == "opencode:default" and "fresh_until" not in row


def test_detector_observation_uses_policy_unit_and_pool():
    hit = {"provider": "opencode", "window": "5h", "observed": {
        "attempt_id": "it-a1", "exhausted_at": "2026-11-09T11:00:00Z",
        "reset_at": "2026-11-09T13:00:00Z"}}
    row = windows.capacity_observation(hit, _policy())
    assert (row["pool"], row["unit"], row["source"]) == (
        "opencode-go:default", "output_tokens", "window-detector")


def _home(tmp_path):
    (tmp_path / "governance").mkdir()
    (tmp_path / "governance" / "allocation.toml").write_text(
        'revision = 5\n\n[providers.opencode]\nunit = "output_tokens"\nexpiring = true\n'
        'pool = "opencode-go:default"\nfreshness_s = 3600\n'
        '[[providers.opencode.windows]]\nname = "5h"\nlength_s = 18000\nbudget = 100\n')


def test_probe_and_windows_record_capacity_observations(tmp_path, monkeypatch):
    _home(tmp_path)
    monkeypatch.setenv("LANECTL_HOME", str(tmp_path))
    monkeypatch.setenv("LANECTL_STATE", str(tmp_path / "state"))
    log = EventLog(tmp_path / "state" / "events.jsonl")
    stats = json.dumps({"range": {"from": 0, "to": 1000}, "sessions": 1,
                        "tokens": {"output": 25}})
    monkeypatch.setattr(probe, "_real_run", lambda argv: stats)
    assert probe._cmd(type("A", (), {"target": "opencode", "record": True})(), log) == 0
    observed = [e for e in log.read() if e["type"] == "capacity.observed"]
    assert [e["data"]["value_kind"] for e in observed] == ["cumulative"]

    claimed = make_event("item.claimed", {
        "attempt_id": "it-a1", "lane": "implement", "model": "opencode-go/x", "worker": "opencode"},
        item_id="it")
    failed = make_event("attempt.finished", {
        "attempt_id": "it-a1", "outcome": "failed", "exit_code": 1, "head_sha": "a" * 40,
        "final_tail": "429 usage limit reached, resets at 2026-11-09T13:00:00Z"}, item_id="it")
    log.append(claimed["type"], claimed["data"], item_id="it")
    log.append(failed["type"], failed["data"], item_id="it")
    assert cli.main(["windows", "--record"]) == 0
    observed = [e for e in log.read() if e["type"] == "capacity.observed"]
    assert observed[-1]["data"]["value_kind"] == "denial"


def test_capacity_cli_prints_qualification(tmp_path, monkeypatch, capsys):
    _home(tmp_path)
    monkeypatch.setenv("LANECTL_HOME", str(tmp_path))
    monkeypatch.setenv("LANECTL_STATE", str(tmp_path / "state"))
    log = EventLog(tmp_path / "state" / "events.jsonl")
    log.append("usage.recorded", {"provider": "opencode", "source": "adapter",
                                  "units": {"output_tokens": 5}})
    assert cli.main(["capacity"]) == 0
    out = capsys.readouterr().out
    assert "opencode" in out and "basis=unknown" in out and "outside_lane=-" in out
    assert cli.main(["capacity", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["qualified"]["opencode"]["lane_used"] == 5
