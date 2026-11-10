"""Lane tests: deploy stage failures, unknown trains and the live projection."""
import os
from pathlib import Path

from lanectl import deploy, runner
from lanectl.adapters import AdapterResult

SUB_TEST = "from calc import sub\n\ndef test_sub():\n    assert sub(5, 3) == 2\n"


def _good(wt):
    (wt / "src" / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
    (wt / "tests" / "test_sub_extra.py").write_text(
        "from calc import sub\n\ndef test_neg():\n    assert sub(1, 2) == -1\n")


def _scripted(edit):
    def fn(*, worktree, **_):
        edit(Path(worktree))
        return AdapterResult("done", 0, "ok", None)
    return fn


def _declare(tmp_path, cmd=None, health="test -f {out}/deployed.txt"):
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    p = Path(os.environ["LANECTL_HOME"]) / "governance" / "repos.toml"
    cmd = cmd or f"touch {out}/deployed.txt"
    p.write_text(p.read_text() + f'''
[repos.target.deploy]
cmd = "{cmd}"
health_cmd = "{health.format(out=out)}"
teardown_cmd = "echo down >> {out}/down.txt"
ttl_s = 60
env_allow = ["PATH"]
''')
    return out


def _train(estate, item="gg-dep"):
    repo, release, log = estate
    release(item, SUB_TEST)
    out = runner.execute(runner.admit("implement", log), log, adapter_fn=_scripted(_good))
    assert "-> candidate" in out, out
    runner.build_train(log, "target")
    return [e for e in log.read() if e["type"] == "train.built"][-1]["data"]["train_id"]


def _of(log, etype):
    return [e["data"] for e in log.read() if e["type"] == etype]


def test_unknown_train_records_nothing(estate):
    assert "unknown" in deploy.deploy_train(estate[2], "train-nope")
    assert _of(estate[2], "train.deployed") == []


def test_failed_deploy_stage_is_recorded_with_tail(estate, tmp_path):
    out = _declare(tmp_path, cmd="echo boom >&2; exit 7")
    tid = _train(estate)
    msg = deploy.deploy_train(estate[2], tid)
    assert "deploy failed" in msg
    (ev,) = _of(estate[2], "train.deployed")
    assert ev["passed"] is False and ev["stage"] == "deploy" and "boom" in ev["tail"]
    (down,) = _of(estate[2], "train.torn_down")
    assert down["reason"] == "deploy-failed" and down["passed"] is True
    assert (out / "down.txt").read_text() == "down\n"
    assert deploy.live(estate[2].read()) == {}


def test_live_keeps_only_latest_passed_undeployed():
    passed_a = {"train_id": "a", "passed": True}
    passed_b = {"train_id": "b", "passed": True}
    events = [
        {"type": "train.deployed", "data": passed_a},
        {"type": "train.deployed", "data": {"train_id": "c", "passed": False}},
        {"type": "train.torn_down", "data": {"train_id": "a"}},
        {"type": "train.deployed", "data": passed_b},
    ]
    assert deploy.live(events) == {"b": passed_b}
