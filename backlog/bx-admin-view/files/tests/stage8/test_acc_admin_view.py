"""Acceptance: management sections in view --html (planner-owned)."""
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from lanectl import cli, view
from lanectl.config import load_lane

ACC = "def test_ok():\n    assert True\n"
CLAIM = {"lane": "implement", "model": "scripted/model", "worker": "scripted"}


def _section(page, sid):
    m = re.search(rf'<section id="{sid}">(.*?)</section>', page, re.S)
    assert m, f"section {sid} missing"
    return m.group(1)


def _seed(estate):
    _, release, log = estate
    for item in ("aa-landed", "bb-parked", "cc-cand", "dd-new", "ee-draft"):
        release(item, ACC)
    home = Path(os.environ["LANECTL_HOME"]) / "backlog"
    toml = home / "ee-draft" / "release.toml"
    toml.write_text(toml.read_text().replace('id = "ee-draft"', 'id = "ee-draft"\ndraft = true'))
    toml = home / "dd-new" / "release.toml"
    toml.write_text(toml.read_text().replace('title = "dd-new"', 'title = "<b>dd</b>"'))
    log.append("item.claimed", dict(CLAIM, attempt_id="aa-landed-a1"), item_id="aa-landed")
    log.append("item.landed", {"attempt_id": "aa-landed-a1", "train_id": "tt", "fix_commits": []},
               item_id="aa-landed")
    log.append("item.parked", {"reason": "protected path touched"}, item_id="bb-parked")
    log.append("item.claimed", dict(CLAIM, attempt_id="cc-cand-a1"), item_id="cc-cand")
    log.append("decision.recorded", {"attempt_id": "cc-cand-a1", "decision": "candidate", "reasons": [],
                                     "rules_revision": 1}, item_id="cc-cand")


def _page(estate, tmp_path):
    _seed(estate)
    out = tmp_path / "view.html"
    assert cli.main(["view", "--html", str(out)]) == 0
    return out.read_text()


def test_backlog_section_lists_open_releases(estate, tmp_path):
    page = _page(estate, tmp_path)
    backlog = _section(page, "backlog")
    for item in ("bb-parked", "cc-cand", "dd-new", "ee-draft"):
        assert item in backlog
    assert "aa-landed" not in backlog and "1 landed" in backlog
    assert "&lt;b&gt;dd&lt;/b&gt;" in backlog and "<b>dd</b>" not in page


def test_attention_section(estate, tmp_path):
    attention = _section(_page(estate, tmp_path), "attention")
    assert "bb-parked" in attention and "protected path touched" in attention
    assert "cc-cand" in attention and "candidate" in attention
    assert "ee-draft" in attention and "draft" in attention
    assert "dd-new" not in attention and "aa-landed" not in attention


def test_lanes_section(estate, tmp_path):
    lanes = _section(_page(estate, tmp_path), "lanes")
    lane = load_lane("implement")
    assert "implement" in lanes and "scripted/model" in lanes
    assert f"1/{lane.caps['accepted_unlanded_max']}" in lanes


def test_governance_section(estate, tmp_path):
    repo, _, _ = estate
    gov = _section(_page(estate, tmp_path), "governance")
    assert "target" in gov and str(repo) in gov


def test_page_links_every_section(estate, tmp_path):
    page = _page(estate, tmp_path)
    for sid in ("backlog", "attention", "lanes", "governance", "items", "report", "capacity", "triage"):
        assert f'href="#{sid}"' in page


def test_render_without_governance_inputs_still_works():
    page = view.render([], datetime(2026, 11, 10, tzinfo=timezone.utc))
    assert '<section id="report">' in page
