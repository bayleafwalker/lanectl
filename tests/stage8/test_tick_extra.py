"""Extra coverage for ``lanectl tick`` (lane-owned)."""
from types import SimpleNamespace

from lanectl import cli, deploy, doctor, runner, tick
from lanectl.doctor import ERROR, OK, Finding


def test_default_run_stops_after_infra_rejection(estate, monkeypatch):
    calls = []

    def fake_admit(lane, log, only=None):
        calls.append(lane)
        return SimpleNamespace(attempt_id="a-1", model="m")

    def fake_execute(claim, log):
        return f"{claim.attempt_id} [m] -> rejected: infra: worker died"

    monkeypatch.setattr(runner, "admit", fake_admit)
    monkeypatch.setattr(runner, "execute", fake_execute)
    out = tick.tick(estate[2], max_items=3,
                    doctor_fn=lambda log: [Finding(OK, "home", "ok")],
                    reap_fn=lambda log: [])
    assert calls == ["implement"]          # the loop stopped at the rejection
    assert out["ran"] == ["claimed a-1 -> m",
                          "a-1 [m] -> rejected: infra: worker died",
                          tick.BREAKER_LINE]


def test_cli_tick_prints_reaped_and_ran_lines(estate, capsys, monkeypatch):
    monkeypatch.setattr(doctor, "run", lambda log: [Finding(doctor.WARN, "policy", "absent")])
    monkeypatch.setattr(deploy, "reap", lambda log: ["train-x: torn down (expired)"])
    monkeypatch.setattr(tick, "_run", lambda log, n, lane: ["nothing ready"])
    rc = cli.main(["tick", "--max", "2", "--lane", "glue"])
    out = capsys.readouterr().out
    assert out.splitlines() == ["tick: doctor=warn reaped=1 ran=1",
                                "train-x: torn down (expired)", "nothing ready"]
    assert rc == 0


def test_cli_tick_exits_one_on_doctor_error(estate, capsys, monkeypatch):
    monkeypatch.setattr(doctor, "run", lambda log: [Finding(ERROR, "home", "missing")])
    rc = cli.main(["tick"])
    out = capsys.readouterr().out
    assert out.splitlines() == ["tick: doctor=error reaped=0 ran=0"]
    assert rc == 1
