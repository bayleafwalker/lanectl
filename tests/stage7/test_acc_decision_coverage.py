"""Acceptance: decision-record coverage (planner-owned)."""
from lanectl import report
from lanectl.contracts import LANE_DECISION_KINDS, make_event
from lanectl.coverage import coverage


def _dec(kind, phase, attempt_id=None, n=0):
    data = {"decision_id": f"dec-{kind}-{phase}-{n}", "kind": kind, "phase": phase, "chosen": None,
            "mechanism": "m", "policy_revision": "r"}
    if attempt_id:
        data["subject"] = {"item_id": "it", "attempt_id": attempt_id}
    return make_event("lane.decision", data, item_id="it")


def _claim(aid):
    return make_event("item.claimed", {"attempt_id": aid, "lane": "implement", "model": "m", "worker": "w"},
                      item_id="it")


def test_dispatch_coverage_joins_claims():
    ev = [_claim("it-a1"), _claim("it-a2"), _dec("dispatch", "applied", "it-a1"),
          _dec("dispatch", "applied", "it-a1", n=1), _dec("dispatch", "proposed", "it-a2"),
          _dec("dispatch", "applied", "zz-a9", n=2)]
    c = coverage(ev)["dispatch"]
    assert c == {"expected": 2, "recorded": 1, "coverage": 0.5}


def test_unknown_without_denominator():
    ev = [_dec("dispatch", "refused"), _dec("dispatch", "refused", n=1),
          make_event("item.requeued", {"reason": "x"}, item_id="it"), _dec("rerun", "applied", "it-a1")]
    c = coverage(ev)
    assert c["refusal"] == {"expected": None, "recorded": 2, "coverage": None}
    assert c["rerun"] == {"expected": 1, "recorded": 1, "coverage": 1.0}
    assert c["escalation"] == {"expected": 0, "recorded": 0, "coverage": None}
    assert set(c) - {"_since"} == set(LANE_DECISION_KINDS) | {"refusal"}


def test_report_section():
    text = report.format_report(report.build_report([_claim("it-a1")]))
    assert "decision_coverage" in text      # header may carry "(since <ts>)" (dr-coverage-gaps)
    assert "  dispatch: recorded=0 expected=1 coverage=0.000" in text
    assert "  refusal: recorded=0 expected=unknown coverage=unknown" in text
