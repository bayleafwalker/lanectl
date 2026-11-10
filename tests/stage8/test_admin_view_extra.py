"""Extra coverage for the management sections of ``view --html``.

The planner-owned acceptance test drives the sections through a seeded
estate; these tests pin the pure ``render`` contract: each optional input
degrades to an "unavailable" note, empty inputs say so, and values from the
releases, lanes and governance are escaped.
"""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from lanectl import view
from lanectl.config import RepoSpec

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


def section(page: str, sid: str) -> str:
    start = page.index(f'<section id="{sid}">')
    return page[start:page.index("</section>", start)]


def draft(release_id: str, title: str) -> SimpleNamespace:
    return SimpleNamespace(id=release_id, title=title, draft=True, repo="target",
                           task_class="glue", size="S", revision=1)


def lane_row(name: str = "implement") -> dict:
    return {
        "lane": name,
        "revision": 3,
        "size_max": "M",
        "max_attempts": 2,
        "timeout_s": 2700,
        "routing": {"scripted/model": 1.0, "other/model": 0.5},
        "caps": {"concurrency": {"used": 1, "limit": 3},
                 "items_per_day": {"used": 2, "limit": 48},
                 "accepted_unlanded_max": {"used": 0, "limit": 8}},
    }


def repo(name: str = "target") -> RepoSpec:
    return RepoSpec(name=name, path=Path("/repos/<target>"), main="main",
                    test_cmd="t", check_cmd="c", worktree_root=Path("/wt"),
                    protected_paths=("a/**", "b/**"), data_class_floor="restricted")


def test_missing_inputs_mark_sections_unavailable():
    page = view.render([], NOW)
    for sid in ("backlog", "attention", "lanes", "governance"):
        assert "unavailable" in section(page, sid), sid
    for sid in ("items", "report", "capacity", "triage"):
        assert f'<section id="{sid}">' in page, sid


def test_nav_links_every_section_in_page_order():
    page = view.render([], NOW)
    links = [f'href="#{sid}"' for sid, _ in view.SECTIONS]
    assert "<nav>" in page
    positions = [page.index(link) for link in links]
    assert positions == sorted(positions)
    assert page.index('<nav>') < page.index('<section id="backlog">')
    assert page.index('<section id="backlog">') < page.index('<section id="items">')


def test_empty_backlog_and_attention_say_so():
    page = view.render([], NOW, releases=[])
    assert "0 landed" in section(page, "backlog")
    assert "no open releases" in section(page, "backlog")
    assert "nothing needs attention" in section(page, "attention")


def test_attention_rows_are_escaped_and_labelled():
    rel = draft("dd-draft", "<b>dd</b>")
    attention = section(view.render([], NOW, releases=[rel]), "attention")
    assert "dd-draft" in attention and "draft" in attention
    assert "&lt;b&gt;dd&lt;/b&gt;" in attention and "<b>dd</b>" not in attention


def test_lanes_rows_show_routing_and_cap_usage():
    lanes = section(view.render([], NOW, lanes=[lane_row()]), "lanes")
    assert "implement" in lanes and "r3" not in lanes and ">3<" in lanes
    assert "scripted/model=1" in lanes and "other/model=0.5" in lanes
    assert "1/3" in lanes and "2/48" in lanes and "0/8" in lanes
    assert "<h2>Lanes</h2>" in lanes


def test_governance_rows_show_path_main_and_floor():
    gov = section(view.render([], NOW, repos={"target": repo()}), "governance")
    assert "target" in gov and "/repos/&lt;target&gt;" in gov
    assert "main" in gov
    assert ">2<" in gov                       # number of protected paths
    assert "restricted" in gov


def test_governance_escapes_repo_names():
    page = view.render([], NOW, repos={"<i>x</i>": repo("<i>x</i>")})
    assert "<i>x</i>" not in page and "&lt;i&gt;x&lt;/i&gt;" in page
