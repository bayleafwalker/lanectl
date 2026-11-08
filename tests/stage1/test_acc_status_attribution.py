"""Acceptance: `lanectl status` metrics separate planner spec gaps from model errors (planner-owned)."""
from lanectl.contracts import make_event
from lanectl.runner import metrics


def _landed(item, fix_classes, model="M1"):
    aid = f"{item}-a1"
    ev = [make_event("experiment.recorded", {"attempt_id": aid, "model": model, "worker": "w", "task_class": "glue",
                                             "decision": "candidate", "elapsed_s": 1}, item_id=item),
          make_event("decision.recorded", {"attempt_id": aid, "decision": "candidate", "reasons": [],
                                           "rules_revision": "v", "by": "gates"}, item_id=item)]
    commits = []
    for i, cls in enumerate(fix_classes):
        commits.append(f"{item}{i}")
        ev.append(make_event("integrator.fix", {"attempt_id": aid, "commit": f"{item}{i}", "fix_class": cls}))
    ev.append(make_event("item.landed", {"attempt_id": aid, "train_id": "tt", "fix_commits": commits}, item_id=item))
    return ev


def test_status_metrics_split_planner_and_model_fixes():
    ev = (_landed("aa", []) + _landed("bb", ["spec-gap"]) + _landed("cc", ["spec-gap", "model-error"])
          + _landed("dd", ["gate-gap"], model="M2"))
    m = metrics(ev)
    assert "model_precision" in m and "fix_classes" in m
    assert m["precision"] == 0.25                      # unchanged raw metric
    assert m["model_precision"] == 0.5                 # aa clean, bb planner-only
    assert m["fix_classes"] == {"spec-gap": 2, "model-error": 1, "gate-gap": 1}
    assert m["per_model"]["M1"]["model_precision"] == round(2 / 3, 3)
    assert m["per_model"]["M2"]["model_precision"] == 0.0
    assert m["per_model"]["M1"]["attempts"] == 3       # existing keys kept


def test_status_metrics_no_ruled_items():
    m = metrics([])
    assert m["model_precision"] is None and m["fix_classes"] == {}
