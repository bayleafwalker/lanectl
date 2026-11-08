"""Integrator fix: the runner passes env (sandbox shim PATH) to adapters."""
import json
import stat

from lanectl.adapters_opencode import run_opencode


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
