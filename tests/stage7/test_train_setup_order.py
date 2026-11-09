"""Train setup must run before the first merge hook, and again after the merges."""
import os
import stat
import subprocess
from pathlib import Path

from lanectl import runner
from tests.seed.test_end_to_end import SUB_TEST, scripted  # estate comes from tests/stage7/conftest.py


def good(wt):
    (wt / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
    (wt / "tests" / "test_sub_extra.py").write_text("from calc import sub\n\ndef test_neg():\n    assert sub(1, 2) == -1\n")


def test_setup_precedes_first_hook_and_reruns_after_merges(estate, tmp_path):
    repo, release, log = estate
    release("add-sub", SUB_TEST)
    c = runner.admit("implement", log)
    assert "-> candidate" in runner.execute(c, log, adapter_fn=scripted(good))

    trace = tmp_path / "trace"
    hooks = repo / "githooks"
    hooks.mkdir()
    h = hooks / "pre-commit"
    h.write_text(f"#!/bin/sh\necho hook >> '{trace}'\n")
    h.chmod(h.stat().st_mode | stat.S_IXUSR)
    subprocess.run(["git", "-C", str(repo), "config", "--local", "core.hooksPath", str(hooks)], check=True)

    repos = Path(os.environ["LANECTL_HOME"]) / "governance" / "repos.toml"
    repos.write_text(repos.read_text().replace("[repos.target]\n",
                                               f"[repos.target]\nsetup_cmd = \"echo setup >> '{trace}'\"\n"))
    runner.build_train(log, "target")
    t = [e["data"] for e in log.read() if e["type"] == "train.built"][-1]
    assert t["attempts"] == [c.attempt_id] and t["excluded"] == [] and t["passed"] is True
    # One setup before the merge commit's hook, one after the merges (deps may change).
    assert trace.read_text().split() == ["setup", "hook", "setup"]
