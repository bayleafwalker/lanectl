"""Acceptance: status and ready show open work by default (planner-owned)."""
from lanectl import cli

ACC = "def test_ok():\n    assert True\n"
CLAIM = {"lane": "implement", "model": "scripted/model", "worker": "scripted"}


def _seed(estate):
    _, release, log = estate
    for item in ("aa-landed", "bb-open"):
        release(item, ACC)
    log.append("release.published", {"release_id": "aa-landed", "revision": 1}, item_id="aa-landed")
    log.append("item.claimed", dict(CLAIM, attempt_id="aa-landed-a1"), item_id="aa-landed")
    log.append("item.landed", {"attempt_id": "aa-landed-a1", "train_id": "tt", "fix_commits": []},
               item_id="aa-landed")
    log.append("release.published", {"release_id": "bb-open", "revision": 1}, item_id="bb-open")
    log.append("item.parked", {"reason": "needs review"}, item_id="bb-open")


def test_status_hides_landed_and_counts_them(estate, capsys):
    _seed(estate)
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "bb-open" in out and "aa-landed" not in out
    assert "landed: 1" in out and "--all" in out


def test_status_all_lists_landed(estate, capsys):
    _seed(estate)
    assert cli.main(["status", "--all"]) == 0
    out = capsys.readouterr().out
    assert "aa-landed" in out and "bb-open" in out


def test_ready_skips_landed_releases(estate, capsys):
    _seed(estate)
    assert cli.main(["ready"]) == 0
    out = capsys.readouterr().out
    assert "bb-open" in out and "aa-landed" not in out


def test_ready_all_marks_landed(estate, capsys):
    _seed(estate)
    assert cli.main(["ready", "--all"]) == 0
    lines = capsys.readouterr().out.splitlines()
    landed = [line for line in lines if "aa-landed" in line]
    assert landed and landed[0].startswith("LANDED")
    assert any("bb-open" in line for line in lines)   # its state label: s3-ready-state


def test_ready_reissued_revision_is_shown_again(estate, capsys):
    _, release, log = estate
    release("cc-reissued", ACC)
    log.append("release.published", {"release_id": "cc-reissued", "revision": 1}, item_id="cc-reissued")
    log.append("item.claimed", dict(CLAIM, attempt_id="cc-reissued-a1"), item_id="cc-reissued")
    log.append("item.landed", {"attempt_id": "cc-reissued-a1", "train_id": "tt", "fix_commits": []},
               item_id="cc-reissued")
    import os
    from pathlib import Path
    toml = Path(os.environ["LANECTL_HOME"]) / "backlog" / "cc-reissued" / "release.toml"
    toml.write_text(toml.read_text().replace('id = "cc-reissued"', 'id = "cc-reissued"\nrevision = 2'))
    assert cli.main(["ready"]) == 0
    assert "cc-reissued" in capsys.readouterr().out
