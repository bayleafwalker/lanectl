"""Acceptance: integrator-approved review-required attempts are ruled (planner-owned)."""
from lanectl.contracts import make_event
from lanectl.report import build_report
from lanectl.runner import metrics


def _attempt(item, fix_classes, approved=False):
    aid = f"{item}-a1"
    gate = "parked" if approved else "candidate"
    ev = [make_event("experiment.recorded", {"attempt_id": aid, "model": "M1", "worker": "w", "task_class": "glue",
                                             "decision": gate, "elapsed_s": 1}, item_id=item),
          make_event("decision.recorded", {"attempt_id": aid, "decision": gate,
                                           "reasons": ["review-required"] if approved else [],
                                           "rules_revision": "v", "by": "gates"}, item_id=item)]
    if approved:
        ev.append(make_event("decision.recorded", {"attempt_id": aid, "decision": "candidate", "reasons": ["ok"],
                                                   "rules_revision": "integrator", "by": "integrator"}, item_id=item))
    commits = []
    for i, cls in enumerate(fix_classes):
        commits.append(f"{item}{i}")
        ev.append(make_event("integrator.fix", {"attempt_id": aid, "commit": f"{item}{i}", "fix_class": cls}))
    ev.append(make_event("item.landed", {"attempt_id": aid, "train_id": "tt", "fix_commits": commits}, item_id=item))
    return ev


def test_approved_attempts_are_ruled_everywhere():
    ev = _attempt("aa", []) + _attempt("bb", ["model-error"], approved=True) + _attempt("cc", [], approved=True)
    m = metrics(ev)
    assert m["ruled"] == 3 and m["gate_accepted"] == 3
    assert m["precision"] == round(2 / 3, 3) and m["model_precision"] == round(2 / 3, 3)
    g = build_report(ev, precision_bar=0.5, min_ruled=1)["by_class"]["glue"]
    assert g["ruled"] == 3 and g["model_precision"] == round(2 / 3, 3)


def test_parked_without_approval_is_not_gate_accepted():
    ev = _attempt("dd", [], approved=True)[:2]   # gates parked it; integrator never approved
    m = metrics(ev)
    assert m["ruled"] == 0 and m["gate_accepted"] == 0
