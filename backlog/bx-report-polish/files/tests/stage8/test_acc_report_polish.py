"""Acceptance: report shows full names; cost feedback labels infra-stopped attempts (planner-owned)."""
from lanectl import report
from lanectl.contracts import make_event
from lanectl.feedback import cost_feedback

M = "opencode-go/deepseek-v4.1-flash"


def _exp(aid, cls="test-generation", model=M):
    return make_event("experiment.recorded", {"attempt_id": aid, "model": model, "worker": "opencode",
                                              "task_class": cls, "decision": "candidate", "elapsed_s": 10.0},
                      item_id=aid.rsplit("-", 1)[0])


def _claim(aid, model=M):
    return make_event("item.claimed", {"attempt_id": aid, "lane": "implement", "model": model,
                                       "worker": "opencode"}, item_id=aid.rsplit("-", 1)[0])


def _decide(aid, reasons, decision="rejected"):
    return make_event("decision.recorded", {"attempt_id": aid, "decision": decision, "reasons": reasons,
                                            "rules_revision": 1}, item_id=aid.rsplit("-", 1)[0])


def test_full_class_and_model_names():
    text = report.format_report(report.build_report([_claim("aa-a1"), _exp("aa-a1")]))
    lines = text.splitlines()
    assert any(line.startswith("test-generation ") for line in lines), text
    assert any(line.startswith(M + " ") for line in lines), text


def test_columns_stay_aligned_with_long_names():
    ev = [_claim("aa-a1"), _exp("aa-a1"), _claim("bb-a1"), _exp("bb-a1", cls="glue")]
    lines = report.format_report(report.build_report(ev)).splitlines()
    header = next(line for line in lines if line.startswith("CLASS"))
    rows = [line for line in lines if line.startswith(("test-generation ", "glue "))]
    att = header.index("ATT") + len("ATT")
    assert len(rows) == 2 and all(row[att - 1] == "1" for row in rows), lines


def test_infra_stopped_attempts_are_counted_and_printed():
    ev = [_claim("aa-a1"), _decide("aa-a1", ["infra: stopped during isolation breach"]),
          _claim("aa-a2"), _decide("aa-a2", ["gate: scope"])]
    row = cost_feedback(ev)[M]
    assert row["attempts"] == 2 and row["infra_attempts"] == 1
    text = report.format_report(report.build_report(ev))
    line = next(line for line in text.splitlines() if line.strip().startswith(M + ":"))
    assert "infra=1" in line
