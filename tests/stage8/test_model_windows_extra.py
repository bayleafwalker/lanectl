"""Model-scoped capacity windows: parsing, projection, isolation and doctor."""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from lanectl import burn, cli, doctor
from lanectl.capacity import (AllocationPolicy, PolicyError, capacity_admission,
                              format_ts, project, qualified)
from lanectl.contracts import make_event

FLASH, PRO = "opencode-go/deepseek-v4.1-flash", "opencode-go/deepseek-v4-pro"
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)


def _raw(*windows):
    return {"revision": 3, "providers": {"opencode": {
        "unit": "output_tokens", "expiring": True, "windows": list(windows)}}}


def _week(name, budget, models=None):
    window = {"name": name, "length_s": 604800, "budget": budget,
              "budget_basis": "verified"}
    if models is not None:
        window["models"] = models
    return window


def _use(model, n, ts="2026-11-07T11:00:00Z", attempt_id=None):
    data = {"provider": "opencode", "source": "adapter", "model": model,
            "units": {"output_tokens": n}}
    if attempt_id is not None:
        data["attempt_id"] = attempt_id
    return make_event("usage.recorded", data, ts=ts)


def _policy(*windows):
    return AllocationPolicy.from_dict(_raw(*windows))


def test_models_must_be_a_list_of_non_empty_strings():
    for bad in ("opencode-go/deepseek-v4-pro", [""], [1], [None], [PRO, ""]):
        raw = _raw(_week("week", 100), _week("pro-week", 100, bad))
        with pytest.raises(PolicyError, match="opencode.*pro-week"):
            AllocationPolicy.from_dict(raw)
    ok = _policy(_week("week", 100), _week("pro-week", 100, [PRO]))
    windows = {w.name: w for w in ok.providers["opencode"].windows}
    assert windows["pro-week"].models == (PRO,) and windows["week"].models == ()
    # An explicit empty array means unscoped, exactly like omitting the key.
    assert _policy(_week("week", 100, [])).providers["opencode"].windows[0].models == ()


def test_scoped_window_ignores_unlisted_models_and_keeps_unscoped_view():
    events = [_use(FLASH, 5000), _use(PRO, 400), _use("other/model", 700)]
    views = project(events, _policy(_week("week", 100000),
                                    _week("pro-week", 1000, [PRO])), NOW)["opencode"]
    assert views["week"]["used"] == 6100 and views["week"]["models"] == []
    assert views["pro-week"]["used"] == 400
    assert views["pro-week"]["remaining"] == 600
    assert views["pro-week"]["models"] == [PRO]


def test_scoped_window_does_not_change_either_admission_path():
    events = [_use(PRO, 900)]
    plain = _policy(_week("week", 100000))
    scoped = _policy(_week("week", 100000), _week("pro-week", 1, [PRO]))
    for policy in (plain, scoped):
        admission = capacity_admission(events, policy, NOW, "opencode", "S")
        assert admission["decision"] == "admit" and admission["burnable"] == 99100
    assert qualified(events, scoped, NOW)["opencode"]["lane_used"] == 900


def test_scoped_window_does_not_change_qualified_admission():
    events = [
        _use(PRO, 9000),
        make_event("capacity.observed", {
            "provider": "opencode", "pool": "p:1", "source": "stats", "unit": "output_tokens",
            "basis": "measured", "observed_at": "2026-11-07T11:50:00Z", "value": 9000,
            "value_kind": "cumulative", "window_start": "2026-11-05T00:00:00Z"},
            ts="2026-11-07T11:50:00Z"),
    ]

    def raw(*windows):
        body = _raw(*windows)
        body["providers"]["opencode"].update(
            {"pool": "p:1", "freshness_s": 3600, "estimates": {"S": 1000}})
        return body

    plain = raw(_week("week", 100000))
    scoped = raw(_week("week", 100000), _week("pro-week", 1, [PRO]))
    for policy in (AllocationPolicy.from_dict(plain), AllocationPolicy.from_dict(scoped)):
        admission = capacity_admission(events, policy, NOW, "opencode", "S")
        assert admission["decision"] == "admit" and admission["burnable"] == 91000


def test_check_ignores_scoped_window_budget_basis_and_expiry():
    # A scoped window with a placeholder basis must not block a verified burn,
    # and its expiry must not become the window the plan burns for.
    events = [
        _use(PRO, 90, "2026-11-07T11:30:00Z"),
        make_event("capacity.observed", {
            "provider": "opencode", "pool": "p:1", "source": "stats", "unit": "output_tokens",
            "basis": "measured", "observed_at": "2026-11-07T11:50:00Z", "value": 90,
            "value_kind": "cumulative", "window_start": "2026-11-05T00:00:00Z"},
            ts="2026-11-07T11:50:00Z"),
    ]
    scoped = {"name": "pro-5h", "length_s": 18000, "budget": 100, "models": [PRO]}
    raw = {"revision": 1, "burn": {"start_within_s": 500000, "min_burnable": 10},
           "providers": {"opencode": {
               "unit": "output_tokens", "expiring": True, "pool": "p:1",
               "freshness_s": 3600, "estimates": {"S": 10},
               "windows": [_week("week", 100000), scoped]}}}
    assert burn.check(events, raw, NOW) == []
    plan = burn.plan_burn(events, raw, NOW, [("aa", "S")],
                          {"concurrency": 1, "accepted_unlanded_max": 1}, 0, 0)
    assert plan is not None and plan["window"] == "week"
    assert plan["items"] == ["aa"]


def test_doctor_warns_per_scoped_window_and_rounds_percent():
    events = [_use(PRO, 805), _use(FLASH, 500000)]
    policy = _policy(_week("pro-week", 1000, [PRO]), _week("week", 1000000))
    (warn,) = doctor.check_model_windows(events, policy, NOW)
    assert warn.level == doctor.WARN and warn.check == "model-windows"
    assert warn.detail == (f"opencode/pro-week: 81% of budget used "
                           f"(models: {PRO})")


def test_doctor_counts_scoped_windows_within_budget():
    events = [_use(PRO, 100), _use(FLASH, 900000)]
    policy = _policy(_week("pro-week", 1000, [PRO]),
                     _week("flash-week", 10_000_000, [FLASH]),
                     _week("week", 1000000))
    (ok,) = doctor.check_model_windows(events, policy, NOW)
    assert ok.level == doctor.OK and ok.detail == "model windows: 2 within budget"
    (none,) = doctor.check_model_windows(events, _policy(_week("week", 1)), NOW)
    assert none.detail == "model windows: 0 within budget"


def test_doctor_run_adds_model_window_findings(estate, capsys):
    _, _, log = estate
    home = Path(os.environ["LANECTL_HOME"])
    (home / "governance" / "allocation.toml").write_text(
        "revision = 3\n[providers.opencode]\nunit = \"output_tokens\"\n"
        "windows = [\n"
        "  { name = \"week\", length_s = 604800, budget = 100000 },\n"
        f"  {{ name = \"pro-week\", length_s = 604800, budget = 1000, models = [\"{PRO}\"] }},\n"
        "]\n")
    log.path.parent.mkdir(parents=True, exist_ok=True)
    ts = format_ts(datetime.now(timezone.utc) - timedelta(hours=1))
    with open(log.path, "a") as fh:
        fh.write(json.dumps(_use(PRO, 900, ts)) + "\n")
    assert cli.main(["doctor"]) == 0
    lines = capsys.readouterr().out.splitlines()
    warn = [line for line in lines if line.startswith("WARN") and " model-windows:" in line]
    assert warn and "opencode/pro-week: 90% of budget used" in warn[0]
