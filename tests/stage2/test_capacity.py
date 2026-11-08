"""Capacity policy loading, projection edge cases and the ``lanectl capacity`` CLI."""
import json
from datetime import datetime, timedelta, timezone

from lanectl import cli
from lanectl.capacity import AllocationPolicy, project
from lanectl.contracts import make_event

T0 = datetime(2026, 11, 8, 10, 0, tzinfo=timezone.utc)
POLICY = AllocationPolicy.from_dict({
    "revision": 3,
    "providers": {
        "opencode-go": {
            "unit": "output_tokens", "expiring": True,
            "windows": [{"name": "5h", "length_s": 18000, "budget": 1000,
                         "anchor": "2026-11-08T10:00:00Z"}],
            "reservations": {"interactive": 0.4},
        },
        "api": {
            "unit": "cost_usd", "expiring": False,
            "windows": [{"name": "day", "length_s": 86400, "budget": 5,
                         "anchor": "2026-11-08T00:00:00Z"}],
            "reservations": {},
        },
    },
})


def usage(provider, n, at, source="adapter", unit="output_tokens"):
    ev = make_event("usage.recorded", {"provider": provider, "source": source, "units": {unit: n}})
    ev["ts"] = at.strftime("%Y-%m-%dT%H:%M:%SZ")
    return ev


def test_from_dict_parses_windows_and_reservations():
    assert POLICY.revision == 3
    assert POLICY.providers["opencode-go"].unit == "output_tokens"
    assert POLICY.providers["opencode-go"].expiring is True
    assert POLICY.providers["opencode-go"].reservations == {"interactive": 0.4}
    assert POLICY.providers["api"].windows[0].length_s == 86400
    assert POLICY.providers["opencode-go"].windows[0].anchor == T0


def test_load_returns_none_when_absent_and_policy_when_present(tmp_path):
    assert AllocationPolicy.load(root=tmp_path) is None
    gov = tmp_path / "governance"
    gov.mkdir()
    (gov / "allocation.toml").write_text(
        'revision = 2\n\n[providers.p]\nunit = "tokens"\nexpiring = true\n'
        '[[providers.p.windows]]\nname = "5h"\nlength_s = 18000\nbudget = 10\n'
    )
    loaded = AllocationPolicy.load(root=tmp_path)
    assert loaded is not None and loaded.revision == 2
    assert loaded.providers["p"].windows[0].budget == 10
    assert loaded.providers["p"].windows[0].anchor is None


def test_usage_for_other_units_and_providers_is_ignored():
    ev = [usage("opencode-go", 50, T0 + timedelta(minutes=1), unit="input_tokens"),
          usage("someone-else", 500, T0 + timedelta(minutes=1)),
          usage("opencode-go", 25, T0 + timedelta(minutes=2))]
    w = project(ev, POLICY, now=T0 + timedelta(minutes=3))["opencode-go"]["5h"]
    assert w["used"] == 25 and w["remaining"] == 975


def test_latest_observation_sets_anchor():
    early = make_event("window.observed", {"provider": "opencode-go", "window": "5h",
                                           "observed": {"reset_at": "2026-11-08T12:00:00Z"}})
    early["ts"] = "2026-11-08T10:30:00Z"
    late = make_event("window.observed", {"provider": "opencode-go", "window": "5h",
                                          "observed": {"reset_at": "2026-11-08T14:00:00Z"}})
    late["ts"] = "2026-11-08T11:00:00Z"
    w = project([late, early], POLICY, now=T0 + timedelta(hours=1))["opencode-go"]["5h"]
    assert (w["window_start"], w["window_end"]) == ("2026-11-08T09:00:00Z", "2026-11-08T14:00:00Z")


def test_expiring_headroom_allows_burn_down():
    w = project([], POLICY, now=T0)["opencode-go"]["5h"]
    assert w["burn_down_allowed"] is True and w["burnable"] == 600
    api = project([], POLICY, now=T0)["api"]["day"]
    assert api["burn_down_allowed"] is False and api["burnable"] == 0


def test_cli_json_projects_the_log(tmp_path, monkeypatch, capsys):
    from lanectl.events import EventLog

    (tmp_path / "governance").mkdir()
    (tmp_path / "governance" / "allocation.toml").write_text(
        'revision = 1\n\n[providers.p]\nunit = "output_tokens"\nexpiring = true\n'
        '[[providers.p.windows]]\nname = "w"\nlength_s = 3600\nbudget = 100\n'
    )
    monkeypatch.setenv("LANECTL_HOME", str(tmp_path))
    monkeypatch.setenv("LANECTL_STATE", str(tmp_path / "state"))
    log = EventLog(tmp_path / "state" / "events.jsonl")
    log.append("usage.recorded", {"provider": "p", "source": "adapter",
                                  "units": {"output_tokens": 7}})
    assert cli.main(["capacity", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["revision"] == 1
    assert payload["providers"]["p"]["w"]["used"] == 7
    assert payload["providers"]["p"]["w"]["remaining"] == 93
