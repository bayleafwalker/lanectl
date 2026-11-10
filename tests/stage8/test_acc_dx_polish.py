"""Acceptance: doctor ignores in-flight drift; capacity prints whole numbers (planner-owned)."""
import os
import subprocess
from pathlib import Path

from lanectl import cli

ACC = "def test_ok():\n    assert True\n"
CLAIM = {"lane": "implement", "model": "scripted/model", "worker": "scripted"}
POLICY = """revision = 3
[providers.opencode]
unit = "output_tokens"
expiring = true
pool = "p:1"
[[providers.opencode.windows]]
name = "5h"
length_s = 18000
budget = 100000
"""


def _move(repo):
    (repo / "moved.txt").write_text("x\n")
    for cmd in (["add", "-A"], ["commit", "-qm", "moved"]):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *cmd], cwd=repo, check=True)


def test_doctor_warns_drift_only_for_waiting_releases(estate, capsys):
    repo, release, log = estate
    for item in ("aa-waiting", "bb-flight", "cc-cand"):
        release(item, ACC)
    log.append("item.claimed", dict(CLAIM, attempt_id="bb-flight-a1"), item_id="bb-flight")
    log.append("item.claimed", dict(CLAIM, attempt_id="cc-cand-a1"), item_id="cc-cand")
    log.append("decision.recorded", {"attempt_id": "cc-cand-a1", "decision": "candidate", "reasons": [],
                                     "rules_revision": 1}, item_id="cc-cand")
    _move(repo)
    cli.main(["doctor"])
    warns = [line for line in capsys.readouterr().out.splitlines() if line.startswith("WARN")]
    assert any("aa-waiting" in w and "base_sha" in w for w in warns), warns
    assert not any("bb-flight" in w or "cc-cand" in w for w in warns), warns


def test_capacity_prints_whole_numbers(estate, capsys):
    _, _, log = estate
    (Path(os.environ["LANECTL_HOME"]) / "governance" / "allocation.toml").write_text(POLICY)
    log.append("capacity.reserved", {"reservation_id": "rr-1", "provider": "opencode", "pool": "p:1",
                                     "unit": "output_tokens", "amount": 24411.825, "attempt_id": "aa-a1"})
    log.append("usage.recorded", {"provider": "opencode", "source": "adapter", "attempt_id": "zz-a1",
                                  "units": {"output_tokens": 1000.6}})
    assert cli.main(["capacity"]) == 0
    out = capsys.readouterr().out
    assert "in_flight=24412" in out and "24411.8" not in out
    assert "used=1001" in out and "1000.6" not in out
