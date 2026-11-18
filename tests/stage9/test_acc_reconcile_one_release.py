import tomllib

import pytest

from lanectl import work
from lanectl.cli import main
from lanectl.events import EventLog


@pytest.mark.parametrize("selector, expected", [(["--release", "chosen"], ["chosen"]),
                                                ([], ["other", "chosen"])])
def test_reconcile_limits_tracker_calls_and_sync_events(tmp_path, monkeypatch, selector, expected):
    governance = tmp_path / "governance"
    governance.mkdir()
    (governance / "repos.toml").write_text("[repos]\n")
    local_state = tmp_path / "state"
    monkeypatch.setenv("LANECTL_HOME", str(tmp_path))
    monkeypatch.setenv("LANECTL_STATE", str(local_state))
    monkeypatch.delenv("LANECTL_STREAM_REPO", raising=False)
    log = EventLog(local_state / "events.jsonl")
    for work_id, item in enumerate(("other", "chosen"), 1):
        log.append("item.landed", {
            "attempt_id": item + "-a1",
            "train_id": item + "-train",
            "fix_commits": [],
            "landed_sha": "a" * 40,
            "work_request": {"id": item, "repo": "example", "work": f"example#{work_id}",
                             "work_complete": True},
        }, item_id=item)
    calls = []

    def sync(rel, train, sha, repos, **kwargs):
        calls.append(rel.id)
        return {"work": rel.work, "train_id": train, "ok": True, "closed": True}

    monkeypatch.setattr(work, "sync", sync)
    assert main(["work", "reconcile", *selector]) == 0
    assert calls == expected
    assert [event["item_id"] for event in log.read() if event["type"] == "work.synced"] == expected

def test_reconcile_preserves_configuration_errors(tmp_path, monkeypatch):
    governance = tmp_path / "governance"
    governance.mkdir()
    (governance / "repos.toml").write_text("[repos")
    monkeypatch.setenv("LANECTL_HOME", str(tmp_path))
    log = EventLog(tmp_path / "state" / "events.jsonl")
    with pytest.raises(tomllib.TOMLDecodeError):
        work.reconcile(log)
