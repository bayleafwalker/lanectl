"""UI-07/08 web integration: permalink work joins, safe references, jumps, accounting."""
import html as _html
import re
import shlex
from urllib.parse import unquote, urlsplit

from lanectl.lifecycle_web import export_lifecycle, locator, render_lifecycle, resolve_locator


def test_work_id_roundtrips_numerically_and_stays_separate_from_release():
    row = dict(item_id="ui-work", work_id=2895, attempt_id="ui-work-a1", facts={})
    url = locator("lanectl", row)
    assert "work_id=2895" in url
    assert resolve_locator(url)["work_id"] == 2895
    page = render_lifecycle("lanectl", row)
    assert "<dt>release</dt><dd><code>ui-work</code></dd>" in page
    assert "<dt>work</dt><dd><code>2895</code></dd>" in page
    assert "--view active" in page


def test_jump_is_shell_safe_and_quotes_identifiers():
    row = dict(item_id="ui work", attempt_id="ui-work-a1", facts={})
    page = render_lifecycle("repo name", row)
    match = re.search(r"Jump: <code>(.*?)</code>", page)
    assert match is not None
    jump = _html.unescape(match.group(1))
    assert shlex.split(jump) == ["lanectl", "tui", "--view", "active",
                                 "--repo", "repo name", "--item", "ui work",
                                 "--attempt", "ui-work-a1"]


def test_runtime_payload_bodies_are_not_searched_for_references():
    row = dict(item_id="ui-work", attempt_id="ui-work-a1", facts={
        "work.evidence.tail-v1": {"state": "observed", "source": "owner", "value": {
            "item": {"ref": "https://example.test/safe", "body": {
                "ref": "https://example.test/private-runtime-body"}}}}})
    page = render_lifecycle("lanectl", row)
    assert "https://example.test/safe" in page
    assert "private-runtime-body" not in page


def test_export_decodes_permalink_path_for_static_serving(tmp_path):
    row = dict(item_id="ui-work", work_id=2895, attempt_id="ui-work-a1", facts={})
    path = export_lifecycle(tmp_path, "repo name", row)
    decoded = unquote(urlsplit(locator("repo name", row)).path).strip("/")
    assert path.relative_to(tmp_path).as_posix() == decoded + "/index.html"
    assert path.is_file()


def test_accounting_absent_says_unavailable_not_zero_cost():
    row = dict(item_id="ui-work", attempt_id="ui-work-a1", facts={})
    page = render_lifecycle("lanectl", row)
    assert "Accounting timeline" in page
    assert "Accounting timeline unavailable" in page


def test_accounting_section_renders_known_subtotals_and_unknowns():
    from lanectl.accounting import accounting_timeline
    from lanectl.contracts import make_event
    policy = {"revision": 19, "providers": {"test": {"prices": {"models": {
        "model-a": {"offpeak": {"output": 2.0}}}}}}}
    events = [make_event("usage.recorded", dict(provider="test", source="adapter",
        model="model-a", units=dict(output_tokens=1_000_000, steps=3)), item_id="ui-work")]
    accounting = accounting_timeline(events, policy, item_id="ui-work")
    accounting.update(source="lanectl.events", checkpoint=42,
                      observed_at="2026-11-12T10:00:00Z")
    row = dict(item_id="ui-work", work_id=2895, attempt_id="ui-work-a1",
               facts={}, accounting=accounting)
    page = render_lifecycle("lanectl", row)
    assert "$2.0000" in page and "unknown" in page
    assert "output_tokens" in page and "19" in page
