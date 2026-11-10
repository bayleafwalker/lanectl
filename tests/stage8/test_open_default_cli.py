"""Regression: ``status`` and ``ready`` put open work first by default.

Companion to the planner-owned acceptance file; these tests pin the behaviours
the acceptance file does not cover (counting several hidden items, the summary
line disappearing under ``--all``, and revisions around the landed cutoff).
"""
import os
from pathlib import Path

from lanectl import cli

ACC = "def test_ok():\n    assert True\n"
CLAIM = {"lane": "implement", "model": "scripted/model", "worker": "scripted"}


def _landed(log, item, revision=1):
    log.append("release.published", {"release_id": item, "revision": revision}, item_id=item)
    log.append("item.claimed", dict(CLAIM, attempt_id=f"{item}-a1"), item_id=item)
    log.append("item.landed", {"attempt_id": f"{item}-a1", "train_id": "tt", "fix_commits": []},
               item_id=item)


def _open(log, item):
    log.append("release.published", {"release_id": item, "revision": 1}, item_id=item)
    log.append("item.parked", {"reason": "needs review"}, item_id=item)


def test_status_counts_every_hidden_landed_item(estate, capsys):
    _, release, log = estate
    for item in ("aa-landed", "bb-landed"):
        release(item, ACC)
        _landed(log, item)
    release("cc-open", ACC)
    _open(log, "cc-open")

    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "cc-open" in out
    assert "aa-landed" not in out and "bb-landed" not in out
    assert "landed: 2 (lanectl status --all to list)" in out


def test_status_all_prints_landed_rows_without_the_summary(estate, capsys):
    _, release, log = estate
    release("aa-landed", ACC)
    _landed(log, "aa-landed")
    release("bb-open", ACC)
    _open(log, "bb-open")

    assert cli.main(["status", "--all"]) == 0
    out = capsys.readouterr().out
    assert "aa-landed" in out and "bb-open" in out
    assert "landed: 1 (" not in out


def test_ready_skips_landed_when_published_revision_is_at_least_the_release(estate, capsys):
    _, release, log = estate
    release("aa-landed", ACC)
    _landed(log, "aa-landed", revision=2)      # release.toml still says revision 1
    release("bb-open", ACC)
    _open(log, "bb-open")

    assert cli.main(["ready"]) == 0
    out = capsys.readouterr().out
    assert "bb-open" in out and "aa-landed" not in out


def test_ready_shows_landed_release_when_it_is_reissued(estate, capsys):
    _, release, log = estate
    release("aa-landed", ACC)
    _landed(log, "aa-landed")
    release("cc-reissued", ACC)
    _landed(log, "cc-reissued")
    toml = Path(os.environ["LANECTL_HOME"]) / "backlog" / "cc-reissued" / "release.toml"
    toml.write_text(toml.read_text().replace('id = "cc-reissued"',
                                             'id = "cc-reissued"\nrevision = 2'))

    assert cli.main(["ready"]) == 0
    out = capsys.readouterr().out
    assert "cc-reissued" in out
    assert "aa-landed" not in out          # current revision stays hidden


def test_ready_all_labels_landed_and_keeps_ready_rows(estate, capsys):
    _, release, log = estate
    release("aa-landed", ACC)
    _landed(log, "aa-landed")
    release("bb-open", ACC)
    _open(log, "bb-open")

    assert cli.main(["ready", "--all"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [line for line in lines if line.startswith("LANDED") and "aa-landed" in line]
    assert [line for line in lines if line.startswith("READY") and "bb-open" in line]
