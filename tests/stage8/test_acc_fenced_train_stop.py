"""An inactive queued start is not cancelled by a refused or uncertain stop."""
import subprocess

import pytest


@pytest.mark.parametrize("outcome", ["acknowledged", "refused", "timeout", "unavailable"])
def test_stop_requires_acknowledgement_before_terminal_proof(monkeypatch, outcome):
    from lanectl import fenced_train as ft
    calls = []
    def stop(argv, **kwargs):
        calls.append(argv)
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(argv, 1)
        if outcome == "unavailable":
            raise OSError("synthetic transport unavailable")
        return subprocess.CompletedProcess(argv, 0 if outcome == "acknowledged" else 1)
    monkeypatch.setattr(ft.subprocess, "run", stop)
    # Could still be queued: this alone is insufficient after a failed stop.
    monkeypatch.setattr(ft, "_active", lambda *args: "inactive")
    unit = "lanectl-train@pending-stop.service"
    assert ft._stop_terminal("synthetic-systemctl", unit) is (outcome == "acknowledged")
    assert calls == [["synthetic-systemctl", "stop", unit]]
