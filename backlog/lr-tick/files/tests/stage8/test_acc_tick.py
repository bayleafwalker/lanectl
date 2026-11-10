"""Acceptance: lanectl tick (planner-owned)."""
from lanectl import cli, tick
from lanectl.doctor import ERROR, OK, WARN, Finding


def _fakes(findings, calls):
    def doctor_fn(log):
        calls.append("doctor")
        return findings

    def reap_fn(log):
        calls.append("reap")
        return ["train-x: torn down (expired)"]

    def run_fn(log, max_items, lane):
        calls.append(("run", max_items, lane))
        return ["claimed a-a1 -> m", "a-a1 [m] -> candidate: all gates passed"]

    return {"doctor_fn": doctor_fn, "reap_fn": reap_fn, "run_fn": run_fn}


def test_tick_runs_doctor_reap_run_in_order(estate):
    calls = []
    out = tick.tick(estate[2], max_items=2, **_fakes([Finding(OK, "home", "ok")], calls))
    assert calls == ["doctor", "reap", ("run", 2, "implement")]
    assert out == {"doctor": "ok", "reaped": ["train-x: torn down (expired)"],
                   "ran": ["claimed a-a1 -> m", "a-a1 [m] -> candidate: all gates passed"],
                   "stopped": None}


def test_warn_still_runs(estate):
    calls = []
    out = tick.tick(estate[2], **_fakes([Finding(WARN, "deploys", "1 live past expires_at")], calls))
    assert out["doctor"] == "warn" and calls[-1] == ("run", 3, "implement")


def test_doctor_error_stops_before_reap_and_run(estate):
    calls = []
    out = tick.tick(estate[2], **_fakes([Finding(ERROR, "home", "missing")], calls))
    assert calls == ["doctor"]
    assert out == {"doctor": "error", "reaped": [], "ran": [], "stopped": "doctor"}


def test_cli_tick_on_a_quiet_estate(estate, capsys):
    rc = cli.main(["tick", "--max", "1"])
    out = capsys.readouterr().out
    assert out.startswith("tick: doctor=")
    assert rc == (1 if "doctor=error" in out else 0)
    assert "reaped=0" in out
