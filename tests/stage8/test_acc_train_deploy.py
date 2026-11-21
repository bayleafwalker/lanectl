"""Acceptance: s3-train-deploy - dev train deploys with a stripped environment."""
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from lanectl import cli, deploy, runner
from lanectl.adapters import AdapterResult
from lanectl.coordination import CoordinationError

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


def _declare(tmp_path, health="test -f {out}/deployed.txt"):
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    p = Path(os.environ["LANECTL_HOME"]) / "governance" / "repos.toml"
    p.write_text(p.read_text() + f'''
[repos.target.deploy]
cmd = "echo $LANE_NAMESPACE $LANE_TRAIN_ID $LANE_TTL_S ${{SECRET_TOKEN:-none}} ${{KEEP_ME:-none}} > {out}/deployed.txt; pwd > {out}/cwd.txt"
health_cmd = "{health.format(out=out)}"
teardown_cmd = "echo down >> {out}/down.txt"
ttl_s = 900
env_allow = ["KEEP_ME", "PATH"]
''')
    return out


def _train(estate, item):
    repo, release, log = estate
    release(item, SUB_TEST)
    out = runner.execute(runner.admit("implement", log), log, adapter_fn=_scripted(_good))
    assert "-> candidate" in out, out
    runner.build_train(log, "target")
    tb = [e for e in log.read() if e["type"] == "train.built"][-1]["data"]
    assert tb["passed"], tb
    return tb


def _of(log, etype):
    return [e["data"] for e in log.read() if e["type"] == etype]


def test_appservice_deploy_refuses_dirty_checked_worktree(estate, tmp_path, monkeypatch):
    from dataclasses import replace

    out = _declare(tmp_path)
    train = _train(estate, "dirty-appservice")
    repos = deploy.load_repos()
    repos["target"] = replace(repos["target"], train_isolation="appservice")
    monkeypatch.setattr(deploy, "load_repos", lambda: repos)
    (Path(train["worktree"]) / "unreviewed.txt").write_text("outside the checked commit")
    assert "checkout is dirty" in deploy.deploy_train(estate[2], train["train_id"])
    assert not (out / "deployed.txt").exists()
    assert _of(estate[2], "train.deployed") == []


def _main(repo):
    return subprocess.run(["git", "-C", repo, "rev-parse", "main"], capture_output=True, text=True).stdout


def test_namespace_and_env_are_stripped(monkeypatch):
    spec = type("S", (), {"env_allow": ("KEEP_ME", "UNSET_ONE", "LANE_CHECKED_SHA"), "ttl_s": 60})()
    monkeypatch.setenv("KEEP_ME", "kept")
    monkeypatch.setenv("SECRET_TOKEN", "leak")
    monkeypatch.setenv("LANE_CHECKED_SHA", "untrusted")
    monkeypatch.delenv("UNSET_ONE", raising=False)
    assert deploy.namespace("train-1") == "lane-dev-train-1"
    assert deploy.deploy_env(spec, "train-1") == {
        "KEEP_ME": "kept", "LANE_NAMESPACE": "lane-dev-train-1",
        "LANE_TRAIN_ID": "train-1", "LANE_TTL_S": "60"}
    assert deploy.deploy_env(spec, "train-1", checked_sha="a" * 40)["LANE_CHECKED_SHA"] == "a" * 40


def test_deploy_passes_records_event_and_sees_only_allowed_env(estate, tmp_path, monkeypatch):
    out = _declare(tmp_path)
    monkeypatch.setenv("SECRET_TOKEN", "leak")
    monkeypatch.setenv("KEEP_ME", "kept")
    tb = _train(estate, "aa-dep")
    tid = tb["train_id"]
    before = datetime.now(timezone.utc)
    deploy.deploy_train(estate[2], tid)
    (ev,) = _of(estate[2], "train.deployed")
    assert ev["passed"] is True and ev["repo"] == "target" and ev["namespace"] == f"lane-dev-{tid}"
    expires = datetime.strptime(ev["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert before + timedelta(seconds=890) <= expires <= before + timedelta(seconds=960)
    assert (out / "deployed.txt").read_text().split() == [f"lane-dev-{tid}", tid, "900", "none", "kept"]
    assert (out / "cwd.txt").read_text().strip() == str(Path(tb["worktree"]).resolve())
    assert tid in deploy.live(estate[2].read())


def test_failed_health_records_failure_and_tears_down(estate, tmp_path):
    out = _declare(tmp_path, health="exit 1")
    tid = _train(estate, "bb-dep")["train_id"]
    deploy.deploy_train(estate[2], tid)
    (ev,) = _of(estate[2], "train.deployed")
    assert ev["passed"] is False and ev["stage"] == "health"
    (down,) = _of(estate[2], "train.torn_down")
    assert down["reason"] == "deploy-failed" and down["passed"] is True
    assert (out / "down.txt").read_text() == "down\n"
    assert deploy.live(estate[2].read()) == {}


def test_repo_without_deploy_records_nothing(estate):
    tid = _train(estate, "cc-dep")["train_id"]
    deploy.deploy_train(estate[2], tid)
    assert _of(estate[2], "train.deployed") == []


def test_land_requires_passed_deploy_then_tears_it_down(estate, tmp_path):
    out = _declare(tmp_path)
    repo = estate[0]
    tid = _train(estate, "dd-dep")["train_id"]
    main_before = _main(repo)
    assert "deploy" in runner.land(estate[2], tid)
    assert _main(repo) == main_before
    deploy.deploy_train(estate[2], tid)
    assert "landed" in runner.land(estate[2], tid)
    (down,) = _of(estate[2], "train.torn_down")
    assert down["reason"] == "landed"
    assert (out / "down.txt").exists()


def test_land_without_deploy_declared_is_unchanged(estate):
    tid = _train(estate, "ee-dep")["train_id"]
    assert "landed" in runner.land(estate[2], tid)


def test_cli_run_and_down(estate, tmp_path, capsys):
    _declare(tmp_path)
    tid = _train(estate, "ff-dep")["train_id"]
    assert cli.main(["deploy", "run", tid]) == 0
    assert cli.main(["deploy", "down", tid]) == 0
    (down,) = _of(estate[2], "train.torn_down")
    assert down["reason"] == "manual"
    assert deploy.live(estate[2].read()) == {}


def test_prepare_failure_keeps_train_pending_and_does_not_contact_deploy(estate, tmp_path, monkeypatch):
    from dataclasses import replace

    out = _declare(tmp_path)
    train = _train(estate, "prep-appservice")
    subprocess.run(["git", "-C", train["worktree"], "clean", "-fd"], check=True, capture_output=True)
    repos = deploy.load_repos()
    config = repos["target"]
    spec = replace(config.deploy, prepare_cmd=f'test -f {out}/ready && echo "$LANE_CHECKED_SHA" > {out}/prepared',
                   cmd=f'test -f {out}/prepared && {config.deploy.cmd}')
    repos["target"] = replace(config, train_isolation="appservice", deploy=spec)
    monkeypatch.setattr(deploy, "load_repos", lambda: repos)
    train_id = train["train_id"]

    assert "preparation failed" in deploy.deploy_train(estate[2], train_id)
    assert _of(estate[2], "train.deployed") == []
    assert _of(estate[2], "train.torn_down") == []
    assert not (out / "deployed.txt").exists()

    (out / "ready").touch()

    class Guard:
        def assert_active(self):
            if (out / "prepared").exists():
                raise CoordinationError("lease lost during preparation")

    with monkeypatch.context() as scoped:
        scoped.setattr(runner._owner_context, "guard", Guard(), raising=False)
        with pytest.raises(CoordinationError, match="lease lost during preparation"):
            deploy.deploy_train(estate[2], train_id)
    assert not (out / "deployed.txt").exists()
    assert _of(estate[2], "train.deployed") == []

    assert "deployed to" in deploy.deploy_train(estate[2], train_id)
    assert (out / "prepared").read_text().strip() == train["checked_sha"]
    assert _of(estate[2], "train.deployed")[-1]["passed"]
