"""Planner contract: a draft release is never ready and never admitted."""
import os
from pathlib import Path

from lanectl import runner
from lanectl.config import load_lane, load_releases, load_repos
from lanectl.ready import readiness

ACC = "def test_ok():\n    assert True\n"


def _draft(item):
    toml = Path(os.environ["LANECTL_HOME"]) / "backlog" / item / "release.toml"
    toml.write_text(toml.read_text().replace(f'id = "{item}"', f'id = "{item}"\ndraft = true'))


def test_draft_blocks_readiness_and_admission(estate):
    _, release, log = estate
    release("aa-draft", ACC)
    _draft("aa-draft")
    rel = next(r for r in load_releases() if r.id == "aa-draft")
    assert rel.draft is True
    assert any("draft" in r for r in readiness(rel, load_lane("implement"), load_repos()))
    assert isinstance(runner.admit("implement", log), str)


def test_published_release_is_admitted(estate):
    _, release, log = estate
    release("bb-ready", ACC)
    assert not isinstance(runner.admit("implement", log), str)
