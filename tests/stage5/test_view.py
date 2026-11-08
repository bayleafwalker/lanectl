"""Static HTML view: counts, escaping, shadows, capacity and triage."""
from datetime import datetime, timezone

from lanectl.contracts import make_event
from lanectl.report import build_report
from lanectl.view import render

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
IID = "aa"


def exp(aid, cls="glue"):
    return make_event("experiment.recorded", {
        "attempt_id": aid, "decision": "candidate", "elapsed_s": 1.0, "gates_failed": [],
        "lane_revision": 2, "model": "m", "rules_revision": "r", "size": "S",
        "task_class": cls, "worker": "opencode"}, item_id=IID)


def test_items_counts_and_event_text_is_escaped():
    claimed = make_event("item.claimed", {"attempt_id": "aa-a1", "lane": "implement",
                                          "model": "m", "worker": "w"}, item_id=IID)
    html = render([claimed, exp("aa-a1", cls="<script>x</script>")], NOW)
    assert '<section id="items">' in html and "<td>claimed</td><td>1</td>" in html
    assert "<script>x</script>" not in html and "&lt;script&gt;x&lt;/script&gt;" in html
    assert "<script src" not in html and "http" not in html.split("</head>")[0]


def test_report_shadow_keys_are_rendered(monkeypatch):
    report = build_report([])
    report.update({
        "shadow_admission": {"recorded": 3, "agreed": 2, "agreement": 0.667},
        "evaluator": {"glue": {"evaluated_ruled": 1, "agreed": 1, "agreement": 1.0}},
        "landing_shadow": {"trains": 1, "matched": 1, "agreement": 1.0}})
    monkeypatch.setattr("lanectl.view.build_report", lambda events: report)
    html = render([], NOW)
    for heading in ("Shadow admission", "Evaluator", "Shadow landing"):
        assert heading in html
    assert "<td>3</td><td>2</td><td>0.667</td>" in html
    assert "<td>glue</td><td>1</td><td>1</td><td>1.000</td>" in html
    assert "<td>1</td><td>1</td><td>1.000</td>" in html


def test_triage_deduplicates_and_escapes():
    ev = [make_event("triage.proposed", {"source": "train", "fingerprint": "f1",
                                         "summary": "<b>boom</b>"})] * 2
    html = render(ev, NOW)
    assert html.count("<td>f1</td>") == 1 and "<td>2</td>" in html
    assert "&lt;b&gt;boom&lt;/b&gt;" in html
    assert "no open triage proposals" in render([], NOW)


def test_capacity_uses_the_policy_and_degrades_without_one(tmp_path, monkeypatch):
    monkeypatch.setenv("LANECTL_HOME", str(tmp_path))
    assert "no allocation policy" in render([], NOW)
    gov = tmp_path / "governance"
    gov.mkdir()
    (gov / "allocation.toml").write_text(
        'revision = 7\n\n[providers.p]\nunit = "tokens"\nexpiring = true\n'
        '[[providers.p.windows]]\nname = "5h"\nlength_s = 18000\nbudget = 10\n'
        'anchor = "2026-11-08T10:00:00Z"\n')
    html = render([], NOW)
    assert "allocation revision 7" in html and "<td>p</td><td>5h</td>" in html
