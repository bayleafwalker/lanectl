"""Acceptance: s3-deploy-reap - list and reap dev deploys; doctor warns on expired ones."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from lanectl import cli, deploy, doctor

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
PAST, FUTURE = "2026-11-10T11:00:00Z", "2026-11-10T13:00:00Z"


def _declare(tmp_path):
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    p = Path(os.environ["LANECTL_HOME"]) / "governance" / "repos.toml"
    p.write_text(p.read_text() + f'''
[repos.target.deploy]
cmd = "true"
health_cmd = "true"
teardown_cmd = "echo $LANE_NAMESPACE >> {out}/down.txt"
''')
    return out


def _deployed(log, train_id, expires_at, passed=True, repo="target"):
    log.append("train.deployed", {"train_id": train_id, "repo": repo, "passed": passed,
                                  "namespace": f"lane-dev-{train_id}", "expires_at": expires_at})


def test_due_classifies_landed_superseded_expired(estate, tmp_path):
    _declare(tmp_path)
    log = estate[2]
    _deployed(log, "train-aa", FUTURE)
    log.append("item.landed", {"attempt_id": "x-a1", "train_id": "train-aa", "fix_commits": []},
               item_id="x1")
    _deployed(log, "train-bb", FUTURE)
    _deployed(log, "train-cc", PAST, repo="other")
    _deployed(log, "train-dd", FUTURE, repo="other2")
    _deployed(log, "train-ee", FUTURE)
    _deployed(log, "train-ff", PAST, passed=False, repo="other3")
    assert deploy.due(log.read(), NOW) == [
        ("train-aa", "landed"), ("train-bb", "superseded"), ("train-cc", "expired")]


def test_reap_tears_down_due_deploys(estate, tmp_path, capsys):
    out = _declare(tmp_path)
    log = estate[2]
    _deployed(log, "train-aa", PAST)
    _deployed(log, "train-zz", "2999-01-01T00:00:00Z", repo="elsewhere")
    lines = deploy.reap(log, now=NOW)
    assert len(lines) == 1 and "train-aa" in lines[0]
    downs = [e["data"] for e in log.read() if e["type"] == "train.torn_down"]
    assert [(d["train_id"], d["reason"]) for d in downs] == [("train-aa", "expired")]
    assert (out / "down.txt").read_text() == "lane-dev-train-aa\n"
    assert list(deploy.live(log.read())) == ["train-zz"]
    assert cli.main(["deploy", "reap"]) == 0


def test_list_text_and_json(estate, tmp_path, capsys):
    _declare(tmp_path)
    log = estate[2]
    assert cli.main(["deploy", "list"]) == 0
    assert "no live deploys" in capsys.readouterr().out
    _deployed(log, "train-aa", "2000-01-01T00:00:00Z")
    assert cli.main(["deploy", "list"]) == 0
    line = capsys.readouterr().out.strip()
    assert line.startswith("lane-dev-train-aa") and "train-aa" in line and line.endswith("EXPIRED")
    assert cli.main(["deploy", "list", "--json"]) == 0
    (row,) = json.loads(capsys.readouterr().out)
    assert row == {"train_id": "train-aa", "namespace": "lane-dev-train-aa", "repo": "target",
                   "expires_at": "2000-01-01T00:00:00Z", "expired": True}


def test_doctor_warns_on_expired_live_deploy(estate, tmp_path):
    _declare(tmp_path)
    log = estate[2]
    assert not [f for f in doctor.run(log, now=NOW) if f.check == "deploys"]
    _deployed(log, "train-aa", PAST)
    found = [f for f in doctor.run(log, now=NOW) if f.check == "deploys"]
    assert len(found) == 1
    finding = found[0]
    assert finding.level == "WARN"
    assert finding.detail == "1 live past expires_at (lanectl deploy reap)"


def test_deploy_run_exit_reflects_the_last_deploy(estate, tmp_path, monkeypatch, capsys):
    _declare(tmp_path)
    log = estate[2]
    log.append("train.built", {"train_id": "train-gg", "repo": "target", "base_sha": "a" * 40,
                               "attempts": [], "passed": True, "worktree": str(tmp_path)})
    _deployed(log, "train-gg", FUTURE)

    def failing(lg, train_id):
        _deployed(lg, train_id, FUTURE, passed=False)
        return f"{train_id}: health failed"

    monkeypatch.setattr(deploy, "deploy_train", failing)
    assert cli.main(["deploy", "run", "train-gg"]) == 1
