"""Deploy list/reap edge cases: ordering, clean reap, and the doctor count."""
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


def _deployed(log, train_id, expires_at, passed=True):
    log.append("train.deployed", {"train_id": train_id, "repo": "target", "passed": passed,
                                  "namespace": f"lane-dev-{train_id}",
                                  "expires_at": expires_at})


def test_list_marks_only_past_deploys(estate, tmp_path, capsys):
    _declare(tmp_path)
    log = estate[2]
    _deployed(log, "train-aa", "2000-01-01T00:00:00Z")
    _deployed(log, "train-bb", FUTURE)
    assert cli.main(["deploy", "list"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "lane-dev-train-aa  train-aa  target  expires 2000-01-01T00:00:00Z  EXPIRED",
        f"lane-dev-train-bb  train-bb  target  expires {FUTURE}",
    ]
    assert cli.main(["deploy", "list", "--json"]) == 0
    assert [row["expired"] for row in json.loads(capsys.readouterr().out)] == [True, False]


def test_reap_does_nothing_when_nothing_is_due(estate, tmp_path, capsys):
    _declare(tmp_path)
    _deployed(estate[2], "train-aa", FUTURE)
    assert deploy.reap(estate[2], now=NOW) == []
    assert cli.main(["deploy", "reap"]) == 0
    assert "nothing to reap" in capsys.readouterr().out
    assert [e["type"] for e in estate[2].read()] == ["train.deployed"]


def test_doctor_counts_every_expired_live_deploy(estate, tmp_path):
    _declare(tmp_path)
    log = estate[2]
    _deployed(log, "train-aa", PAST)
    _deployed(log, "train-bb", PAST, passed=False)   # not live: not counted
    _deployed(log, "train-cc", PAST)
    (found,) = [f for f in doctor.run(log, now=NOW) if f.check == "deploys"]
    assert found.level == "WARN"
    assert found.detail == "2 live past expires_at (lanectl deploy reap)"


def test_failed_rerun_exits_nonzero_after_an_earlier_pass(estate, tmp_path, monkeypatch):
    _declare(tmp_path)
    log = estate[2]
    _deployed(log, "train-gg", FUTURE)

    def failing(lg, train_id):
        _deployed(lg, train_id, FUTURE, passed=False)
        return f"{train_id}: health failed"

    monkeypatch.setattr(deploy, "deploy_train", failing)
    assert cli.main(["deploy", "run", "train-gg"]) == 1
