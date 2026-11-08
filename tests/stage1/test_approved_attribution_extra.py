"""Approved review-required attempts reach status metrics and per-model groups."""
from lanectl.contracts import make_event
from lanectl.report import attribution, build_report
from lanectl.runner import metrics


def _attempt(item, model, fix_classes=(), approved=False):
    aid = f"{item}-a1"
    gate = "parked" if approved else "candidate"
    ev = [make_event("experiment.recorded", {"attempt_id": aid, "model": model, "worker": "w",
                                             "task_class": "glue", "decision": gate,
                                             "elapsed_s": 1}, item_id=item),
          make_event("decision.recorded", {"attempt_id": aid, "decision": gate,
                                           "reasons": ["review-required"] if approved else [],
                                           "rules_revision": "v", "by": "gates"}, item_id=item)]
    if approved:
        ev.append(make_event("decision.recorded", {"attempt_id": aid, "decision": "candidate",
                                                   "reasons": ["ok"], "rules_revision": "integrator",
                                                   "by": "integrator"}, item_id=item))
    commits = []
    for i, cls in enumerate(fix_classes):
        commits.append(f"{item}{i}")
        ev.append(make_event("integrator.fix", {"attempt_id": aid, "commit": f"{item}{i}",
                                                "fix_class": cls}))
    ev.append(make_event("item.landed", {"attempt_id": aid, "train_id": "tt",
                                         "fix_commits": commits}, item_id=item))
    return ev


def test_approval_is_shared_gate_acceptance_across_report_and_status():
    ev = (_attempt("aa", "M1") + _attempt("bb", "M1", ["model-error"], approved=True)
          + _attempt("cc", "M2", approved=True))

    attributed = attribution(ev)
    assert attributed["gate_ok"] == {"aa-a1", "bb-a1", "cc-a1"}
    assert attributed["ruled"] == {"aa-a1", "bb-a1", "cc-a1"}

    m = metrics(ev)
    assert m["gate_accepted"] == 3 and m["ruled"] == 3
    assert m["precision"] == round(2 / 3, 3)
    assert m["per_model"]["M1"]["model_precision"] == round(1 / 2, 3)
    assert m["per_model"]["M2"]["model_precision"] == 1.0

    r = build_report(ev, precision_bar=0.5, min_ruled=1)
    assert r["by_class"]["glue"]["gate_accepted"] == 3
    assert r["by_class"]["glue"]["ruled"] == 3
    assert r["by_model"]["M1"]["ruled"] == 2
