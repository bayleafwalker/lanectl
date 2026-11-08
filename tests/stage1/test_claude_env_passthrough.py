"""Integrator fix: the Claude adapter launches the claude found on the runner's env PATH."""
import json
import stat

from lanectl.adapters_claude import run_claude


def test_env_path_selects_shim(tmp_path):
    shim = tmp_path / "shim" / "claude"
    shim.parent.mkdir()
    shim.write_text("#!/bin/sh\necho '" + json.dumps({"type": "result", "is_error": False, "result": "via-shim",
                    "usage": {}, "total_cost_usd": 0, "num_turns": 1}) + "'\n")
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    wt = tmp_path / "wt"
    wt.mkdir()
    r = run_claude(model="claude-haiku-5-5", worktree=wt, prompt="p", status_file=tmp_path / "s.json",
                   timeout_s=10, external=False, env={"PATH": f"{shim.parent}:/usr/bin:/bin"})
    assert r.outcome == "done" and r.final_tail == "via-shim"
