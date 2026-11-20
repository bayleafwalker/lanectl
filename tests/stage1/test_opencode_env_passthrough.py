"""Integrator fix: the runner passes env (sandbox shim PATH) to adapters."""
import json
import stat
import subprocess
import threading

from lanectl import sandbox
from lanectl.adapters_opencode import run_appservice_opencode, run_opencode
from lanectl.resident_gateway import GO_ROUTE


def test_env_selects_the_opencode_on_its_path(tmp_path):
    shim = tmp_path / "shim" / "opencode"
    shim.parent.mkdir()
    shim.write_text("#!/bin/sh\necho '{\"type\":\"text\",\"part\":{\"type\":\"text\",\"text\":\"via-shim\"}}'\n")
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    wt = tmp_path / "wt"
    wt.mkdir()
    r = run_opencode(model="m", worktree=wt, prompt="-starts-with-dash", status_file=tmp_path / "s.json",
                     timeout_s=10, external=True, env={"PATH": f"{shim.parent}:/usr/bin:/bin"})
    assert r.outcome == "done" and r.final_tail == "via-shim"
    assert json.loads((tmp_path / "s.json").read_text())["outcome"] == "done"


def test_appservice_opencode_records_cancelled_execution(tmp_path, monkeypatch):
    cancelled = threading.Event()
    monkeypatch.setattr("shutil.which", lambda _: "/bin/opencode")

    config = tmp_path / "image-config.json"

    def launch(checkout, argv, timeout, *, cancel_event, opencode_config):
        assert checkout == tmp_path and timeout == 10 and cancel_event is cancelled
        assert opencode_config == config
        assert argv == ["/bin/opencode", "run", "--standalone", "--format", "json",
                        "--model", "resident-gateway/deepseek-v4.1-flash", "--", "-starts-with-dash"]
        cancel_event.set()
        output = '{"type":"text","part":{"type":"text","text":"DISPATCH_OUTCOME: ESCALATED"}}'
        return subprocess.CompletedProcess(argv, 130, output, "cancelled")

    monkeypatch.setattr(sandbox, "run_appservice_command", launch)
    status = tmp_path / "status.json"
    result = run_appservice_opencode(model=GO_ROUTE, worktree=tmp_path, prompt="-starts-with-dash",
                                    status_file=status, timeout_s=10, config=config, cancel_event=cancelled)
    assert (result.outcome, result.exit_code) == ("failed", 130)
    assert json.loads(status.read_text())["usage"] == result.usage
