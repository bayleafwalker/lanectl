"""Acceptance: integrator skill content (planner-owned)."""
from pathlib import Path

SKILL = Path(__file__).parents[2] / ".claude" / "skills" / "lane-integrator" / "SKILL.md"


def test_skill_frontmatter_and_commands():
    assert SKILL.is_file(), "skill not written yet"
    text = SKILL.read_text()
    head = text.split("---")[1]
    assert "name: lane-integrator" in head and "description:" in head
    for needle in ("lanectl approve", "lanectl train", "lanectl plan-landing", "lanectl land",
                   "lanectl reject", "lanectl triage scan --record", "fix(<attempt_id>): [",
                   "governance/integrator.toml", "fix_budget_lines", "allowed_fix_classes"):
        assert needle in text, needle
    assert len(text.splitlines()) <= 120
