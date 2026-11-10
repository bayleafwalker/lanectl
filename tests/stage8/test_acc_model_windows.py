"""Acceptance: model-scoped capacity windows (planner-owned)."""
from datetime import datetime, timezone

import pytest

from lanectl import burn, doctor
from lanectl.capacity import AllocationPolicy, PolicyError, project
from lanectl.contracts import make_event

FLASH, PRO = "opencode-go/deepseek-v4.1-flash", "opencode-go/deepseek-v4-pro"
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)


def _raw(pro_budget=1000):
    return {"revision": 1, "providers": {"opencode": {
        "unit": "output_tokens", "expiring": True,
        "windows": [
            {"name": "week", "length_s": 604800, "budget": 100000},
            {"name": "pro-week", "length_s": 604800, "budget": pro_budget, "models": [PRO]},
        ]}}}


def _use(model, n):
    return make_event("usage.recorded", {"provider": "opencode", "source": "adapter",
                                         "model": model, "units": {"output_tokens": n}},
                      ts="2026-11-07T11:00:00Z")


EVENTS = [_use(FLASH, 5000), _use(PRO, 900)]


def test_models_parse_and_reject_bad_values():
    policy = AllocationPolicy.from_dict(_raw())
    windows = {w.name: w for w in policy.providers["opencode"].windows}
    assert windows["pro-week"].models == (PRO,) and windows["week"].models == ()
    bad = _raw()
    bad["providers"]["opencode"]["windows"][1]["models"] = [""]
    with pytest.raises(PolicyError, match="pro-week"):
        AllocationPolicy.from_dict(bad)


def test_scoped_window_counts_only_its_models():
    views = project(EVENTS, AllocationPolicy.from_dict(_raw()), NOW)["opencode"]
    assert views["week"]["used"] == 5900 and views["week"]["models"] == []
    assert views["pro-week"]["used"] == 900 and views["pro-week"]["models"] == [PRO]


def test_burn_ignores_scoped_windows():
    # Same estate as tests/stage8/test_acc_burn_windows.py: burnable 90000, three items.
    from tests.stage8 import test_acc_burn_windows as bw
    scoped = {"name": "m-week", "length_s": 604800, "budget": 1, "budget_basis": "verified",
              "models": ["m"]}                    # exhausted many times over by model "m"
    plain = burn.plan_burn(bw.EVENTS, bw._raw(bw.FIVE_H, bw._week(1_000_000)), bw.LATE,
                           bw.READY, bw.CAPS, 0, 0)
    with_scoped = burn.plan_burn(bw.EVENTS, bw._raw(bw.FIVE_H, bw._week(1_000_000), scoped),
                                 bw.LATE, bw.READY, bw.CAPS, 0, 0)
    assert plain is not None and plain["burnable"] == 90000
    assert with_scoped is not None
    assert with_scoped["burnable"] == plain["burnable"] and with_scoped["items"] == plain["items"]


def test_doctor_warns_at_eighty_percent():
    policy = AllocationPolicy.from_dict(_raw())
    (warn,) = doctor.check_model_windows(EVENTS, policy, NOW)
    assert warn.level == doctor.WARN and warn.check == "model-windows"
    assert "opencode/pro-week: 90% of budget used" in warn.detail and PRO in warn.detail
    (ok,) = doctor.check_model_windows(EVENTS, AllocationPolicy.from_dict(_raw(10000)), NOW)
    assert ok.level == doctor.OK and "1 within budget" in ok.detail
