"""Extra reaper coverage: threshold behaviour and CLI wiring."""
from datetime import datetime, timezone

from lanectl import cli
from lanectl.events import EventLog, project_items
from lanectl.reap import reap

LANE = """\
lane = "implement"
revision = 1
[eligibility]
size_max = "M"
[routing]
weights = { "m" = 1.0 }
retry = "different_model"
max_attempts = 1
[caps]
concurrency = 1
items_per_day = 1
accepted_unlanded_max = 1
[gates]
size_budget_lines = { S = 1, M = 1, L = 1 }
protected_paths = []
dependency_manifests = []
test_globs = []
forbidden_added_patterns = []
"""


def _claim(log, item, n):
    log.append("item.claimed", {"attempt_id": f"{item}-a{n}", "lane": "implement", "model": "m",
                                "worker": "w", "release_revision": 1}, item_id=item)


def test_reap_leaves_fresh_claims_alone(tmp_path):
    log = EventLog(tmp_path / "e.jsonl")
    _claim(log, "fresh", 1)
    assert reap(log, now=datetime.now(timezone.utc), older_than_s=3600, max_attempts=2) == []
    assert project_items(log.read())["fresh"].state == "claimed"


def test_cli_reap_closes_stale_attempt(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "governance" / "lanes").mkdir(parents=True)
    (home / "governance" / "lanes" / "implement.toml").write_text(LANE)
    monkeypatch.setenv("LANECTL_HOME", str(home))
    monkeypatch.setenv("LANECTL_STATE", str(tmp_path / "state"))
    log = EventLog()
    _claim(log, "stale", 1)

    assert cli.main(["reap", "--older-than", "0"]) == 0
    assert project_items(log.read())["stale"].state == "parked"
