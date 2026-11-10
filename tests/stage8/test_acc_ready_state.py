"""Acceptance: s3-ready-state - ready labels in-flight items by their state."""
import os
from pathlib import Path

from lanectl import cli

ACC = "def test_ok():\n    assert True\n"
CLAIM = {"lane": "implement", "model": "scripted/model", "worker": "scripted"}


def _label(out, item):
    (line,) = [ln for ln in out.splitlines() if ln.split()[-1:] == [item]]
    return line.split()[0]


def _publish(log, item):
    log.append("release.published", {"release_id": item, "revision": 1}, item_id=item)


def test_in_flight_items_show_state(estate, capsys):
    _, release, log = estate
    for item in ("aa-claimed", "bb-parked", "cc-new"):
        release(item, ACC)
        _publish(log, item)
    log.append("item.claimed", dict(CLAIM, attempt_id="aa-claimed-a1"), item_id="aa-claimed")
    log.append("item.parked", {"reason": "needs review"}, item_id="bb-parked")
    assert cli.main(["ready"]) == 0
    out = capsys.readouterr().out
    assert _label(out, "aa-claimed") == "CLAIMED"
    assert _label(out, "bb-parked") == "PARKED"
    assert _label(out, "cc-new") == "READY"
    assert "aa-claimed\n    -" not in out


def test_reissued_parked_item_is_judged_by_readiness(estate, capsys):
    _, release, log = estate
    release("dd-reissued", ACC)
    _publish(log, "dd-reissued")
    log.append("item.parked", {"reason": "spec gap"}, item_id="dd-reissued")
    toml = Path(os.environ["LANECTL_HOME"]) / "backlog" / "dd-reissued" / "release.toml"
    toml.write_text(toml.read_text().replace('id = "dd-reissued"', 'id = "dd-reissued"\nrevision = 2'))
    assert cli.main(["ready"]) == 0
    assert _label(capsys.readouterr().out, "dd-reissued") == "READY"
