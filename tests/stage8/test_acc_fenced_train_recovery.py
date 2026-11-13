"""Post-review receipt completion and uncertain-launch regressions."""
import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest


def test_every_submitted_request_has_a_fresh_nonce():
    from lanectl import fenced_train as ft
    repo = SimpleNamespace(setup_cmd="")
    first = json.loads(ft._request(repo, "true", 60))
    second = json.loads(ft._request(repo, "true", 60))
    assert re.fullmatch("[0-9a-f]{32}", first["nonce"])
    assert first["nonce"] != second["nonce"]


@pytest.mark.parametrize("interrupted", [False, True])
def test_uncertain_start_stops_before_cleanup_and_retains_unknown_liveness(tmp_path, monkeypatch, interrupted):
    from lanectl import fenced_train as ft
    spool = tmp_path / "trains"
    results = tmp_path / "results"
    spool.mkdir()
    results.mkdir()
    monkeypatch.setattr(ft, "TRAIN_ROOT", spool)
    monkeypatch.setattr(ft, "RESULT_ROOT", results)
    monkeypatch.setattr(ft, "_tools", lambda: ("synthetic-systemctl", None))
    def stage(checkout, dest):
        dest.mkdir()
        return "a" * 40, [], {}
    monkeypatch.setattr(ft, "_stage", stage)
    starts, stops = [], []
    def start(tool, unit):
        starts.append(unit)
        if interrupted:
            raise KeyboardInterrupt("lost acknowledgement")
        raise ft.FenceError("start acknowledgement lost after possible admission")
    def stop(tool, unit):
        stops.append(unit)
        return False
    monkeypatch.setattr(ft, "_start", start)
    monkeypatch.setattr(ft, "_stop_terminal", stop)
    repo = SimpleNamespace(setup_cmd="")
    if interrupted:
        with pytest.raises(KeyboardInterrupt) as raised:
            ft.run_command(repo, Path("unused"), "true", timeout_s=1)
        assert "orphan" in str(raised.value) and starts[0] in str(raised.value)
    else:
        result = ft.run_command(repo, Path("unused"), "true", timeout_s=1)
        assert result.returncode != 0
        assert "orphan" in result.stderr and starts[0] in result.stderr
    assert starts == stops and len(stops) == 1
    assert len(list(spool.iterdir())) == 1
