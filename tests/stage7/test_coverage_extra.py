"""Unit: decision-record coverage joins independent denominators."""
from lanectl.coverage import coverage
from lanectl.contracts import make_event


def _dec(kind, phase, n=0, attempt_id=None):
    data = {"decision_id": f"dec-{kind}-{phase}-{n}", "kind": kind, "phase": phase,
            "chosen": None, "mechanism": "m", "policy_revision": "r"}
    if attempt_id:
        data["subject"] = {"item_id": "it", "attempt_id": attempt_id}
    return make_event("lane.decision", data, item_id="it")


def _ev(etype, data):
    return make_event(etype, data, item_id="it")


def test_each_denominator_and_phase():
    ev = [
        _ev("item.requeued", {"reason": "x"}),
        _dec("rerun", "applied"), _dec("rerun", "applied", n=1),
        _ev("item.parked", {"reason": "x"}), _ev("item.parked", {"reason": "y"}),
        _dec("escalation", "applied"),
        _ev("burn.planned", {"provider": "p", "window": "5h", "burnable": 1, "items": []}),
        _ev("burn.planned", {"provider": "p", "window": "5h", "burnable": 1, "items": []}),
        _ev("burn.planned", {"provider": "p", "window": "5h", "burnable": 1, "items": []}),
        _dec("allocation", "proposed"), _dec("allocation", "applied", n=1),
        _ev("evaluation.recorded", {"attempt_id": "a", "evaluator": "e", "verdict": "accept",
                                    "rules_revision": "r"}),
        _ev("evaluation.recorded", {"attempt_id": "b", "evaluator": "e", "verdict": "reject",
                                    "rules_revision": "r"}),
        _dec("acceptance", "proposed"), _dec("acceptance", "applied", n=1),
        _dec("acceptance", "refused", n=2),
    ]
    c = coverage(ev)
    assert c["rerun"] == {"expected": 1, "recorded": 2, "coverage": 1.0}
    assert c["escalation"] == {"expected": 2, "recorded": 1, "coverage": 0.5}
    assert c["allocation"] == {"expected": 3, "recorded": 1, "coverage": 0.333}
    assert c["acceptance"] == {"expected": 2, "recorded": 3, "coverage": 1.0}
    assert c["refusal"] == {"expected": None, "recorded": 1, "coverage": None}
    assert c["dispatch"] == {"expected": 0, "recorded": 0, "coverage": None}


def test_dispatch_needs_a_claimed_attempt_and_subject():
    ev = [
        _ev("item.claimed", {"attempt_id": "it-a1", "lane": "implement",
                             "model": "m", "worker": "w"}),
        _dec("dispatch", "applied"),                       # no subject
        _dec("dispatch", "applied", attempt_id="zz-a9"),   # unclaimed attempt
        _dec("dispatch", "applied", attempt_id="it-a1"),
    ]
    assert coverage(ev)["dispatch"] == {"expected": 1, "recorded": 1, "coverage": 1.0}


def test_format_is_sorted_with_unknowns():
    from lanectl import report
    text = report.format_report(report.build_report([]))
    assert "decision_coverage" in text
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("decision_coverage"))
    kinds = [line.split(":")[0].strip() for line in lines[start + 1:start + 7]]
    assert kinds == sorted(kinds) == ["acceptance", "allocation", "dispatch",
                                      "escalation", "refusal", "rerun"]
    assert lines[start + 1] == "  acceptance: recorded=0 expected=0 coverage=unknown"
