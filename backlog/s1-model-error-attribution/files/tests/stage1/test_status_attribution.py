"""Status metrics attribute fixes to planner, gates or model (see report.py).

Planner-rewritten 2026-11-08 when the attribution rule changed (gate-gap moved off the model)."""
from lanectl.contracts import make_event
from lanectl.runner import metrics


def _landed(item, fix_classes, model="M1"):
    aid = f"{item}-a1"
    ev = [make_event("experiment.recorded", {"attempt_id": aid, "model": model, "worker": "w",
                                             "task_class": "glue", "decision": "candidate",
                                             "elapsed_s": 1}, item_id=item),
          make_event("decision.recorded", {"attempt_id": aid, "decision": "candidate",
                                           "reasons": [], "rules_revision": "v", "by": "gates"},
                     item_id=item)]
    commits = []
    for i, cls in enumerate(fix_classes):
        commits.append(f"{item}{i}")
        ev.append(make_event("integrator.fix", {"attempt_id": aid, "commit": f"{item}{i}",
                                                "fix_class": cls}))
    ev.append(make_event("item.landed", {"attempt_id": aid, "train_id": "tt",
                                         "fix_commits": commits}, item_id=item))
    return ev


def test_per_model_fix_classes_and_planner_attribution():
    ev = (_landed("aa", [], model="M1") + _landed("bb", ["spec-gap"], model="M1")
          + _landed("cc", ["gate-gap"], model="M2"))
    m = metrics(ev)
    assert m["model_precision"] == 1.0
    assert m["per_model"]["M1"]["fix_classes"] == {"spec-gap": 1}
    assert m["per_model"]["M2"]["fix_classes"] == {"gate-gap": 1}
    assert m["per_model"]["M1"]["attempts"] == 2          # existing keys kept
