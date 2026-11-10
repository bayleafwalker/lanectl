"""Stage-8 extras: drift warnings skip in-flight work; capacity text is whole numbers.

The acceptance file (``test_acc_dx_polish.py``) covers one waiting and two
in-flight items and two capacity figures; these tests widen the same outcomes
to every item state and to every figure the text view prints, and pin the JSON
view to the exact ledger values.
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

from lanectl import cli
from lanectl.contracts import make_event

ACC = "def test_ok():\n    assert True\n"
CLAIM = {"lane": "implement", "model": "scripted/model", "worker": "scripted"}
POLICY = """revision = 3
[providers.opencode]
unit = "output_tokens"
expiring = true
pool = "p:1"
[providers.opencode.reservations]
interactive = 0.1
[[providers.opencode.windows]]
name = "5h"
length_s = 18000
budget = 100000
"""


def _move(repo: Path) -> None:
    (repo / "moved.txt").write_text("x\n")
    for cmd in (["add", "-A"], ["commit", "-qm", "moved"]):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *cmd],
                       cwd=repo, check=True)


def _append(log, events) -> None:
    log.path.parent.mkdir(parents=True, exist_ok=True)
    with open(log.path, "a") as fh:
        for event in events:
            fh.write(json.dumps(event) + "\n")


def _e(item: str, etype: str, data: dict) -> dict:
    return make_event(etype, data, item_id=item)


def _claimed(item: str) -> dict:
    return _e(item, "item.claimed", dict(CLAIM, attempt_id=f"{item}-a1"))


def _finished(item: str) -> dict:
    return _e(item, "attempt.finished", {"attempt_id": f"{item}-a1", "outcome": "ok",
                                         "exit_code": 0, "head_sha": "a" * 40})


def _gated(item: str) -> dict:
    return _e(item, "gate.result", {"attempt_id": f"{item}-a1", "gate": "acceptance",
                                    "passed": True, "violations": []})


def _decision(item: str, decision: str) -> dict:
    return _e(item, "decision.recorded", {"attempt_id": f"{item}-a1", "decision": decision,
                                          "reasons": [], "rules_revision": 1})


#: Item states that wait for a lane: a rebase is the right advice.
WAITING = {
    "aa-new": [],
    "bb-ready": [lambda: _e("bb-ready", "release.published",
                            {"release_id": "bb-ready", "revision": 1})],
    "cc-requeued": [lambda: _e("cc-requeued", "item.requeued", {"reason": "retry"})],
    "dd-parked": [lambda: _e("dd-parked", "item.parked", {"reason": "needs a decision"})],
    "ee-rejected": [lambda: _decision("ee-rejected", "rejected")],
}

#: Item states where an attempt is (or was) moving through a lane.
IN_FLIGHT = {
    "ff-claimed": [lambda: _claimed("ff-claimed")],
    "gg-implemented": [lambda: _claimed("gg-implemented"), lambda: _finished("gg-implemented")],
    "hh-gated": [lambda: _claimed("hh-gated"), lambda: _finished("hh-gated"),
                 lambda: _gated("hh-gated")],
    "ii-candidate": [lambda: _claimed("ii-candidate"),
                     lambda: _decision("ii-candidate", "candidate")],
    "jj-in-train": [lambda: _claimed("jj-in-train"),
                    lambda: _decision("jj-in-train", "candidate"),
                    lambda: _e("jj-in-train", "train.built",
                               {"train_id": "t1", "base_sha": "a" * 40,
                                "attempts": ["jj-in-train-a1"], "passed": True})],
}


def test_doctor_warns_drift_for_waiting_states_only(estate, capsys):
    repo, release, log = estate
    for item, events in {**WAITING, **IN_FLIGHT}.items():
        release(item, ACC)
        _append(log, [build() for build in events])
    _move(repo)
    assert cli.main(["doctor"]) == 0
    warns = [line for line in capsys.readouterr().out.splitlines()
             if line.startswith("WARN") and "base_sha" in line]
    for item in WAITING:
        assert any(item in warn for warn in warns), (item, warns)
    for item in IN_FLIGHT:
        assert not any(item in warn for warn in warns), (item, warns)


def test_capacity_text_is_whole_numbers_and_json_is_exact(estate, capsys):
    _, _, log = estate
    (Path(os.environ["LANECTL_HOME"]) / "governance" / "allocation.toml").write_text(POLICY)
    log.append("capacity.reserved", {"reservation_id": "rr-1", "provider": "opencode",
                                     "pool": "p:1", "unit": "output_tokens",
                                     "amount": 24411.825, "attempt_id": "aa-a1"})
    log.append("usage.recorded", {"provider": "opencode", "source": "adapter",
                                  "attempt_id": "zz-a1", "units": {"output_tokens": 1000.6}})

    assert cli.main(["capacity"]) == 0
    lines = capsys.readouterr().out.splitlines()
    pool_line = next(line for line in lines if "in_flight=" in line)
    assert "outside_lane=-" in pool_line
    assert "in_flight=24412" in pool_line, pool_line
    window_line = next(line for line in lines if "used=" in line)
    assert "used=1001" in window_line, window_line
    assert "remaining=98999" in window_line, window_line
    for field in ("reserved", "burnable"):
        rendered = window_line.split(f"{field}=")[1].split()[0]
        assert rendered.lstrip("-").isdigit(), window_line
    assert "24411.8" not in "\n".join(lines) and "1000.6" not in "\n".join(lines)

    assert cli.main(["capacity", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["qualified"]["opencode"]["in_flight"] == pytest.approx(24411.825)
    window = data["providers"]["opencode"]["5h"]
    assert window["used"] == pytest.approx(1000.6)
    assert window["remaining"] == pytest.approx(100000 - 1000.6)
