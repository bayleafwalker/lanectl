"""Acceptance: precision split by who caused the fix (planner-owned).

`precision` stays as is. `model_precision` treats spec-gap fixes as the
planner's fault: an attempt whose only fixes are spec-gap counts as clean.
"""
from lanectl.contracts import make_event
from lanectl.report import build_report


def _landed(item, cls_fixes):
    aid = f"{item}-a1"
    ev = [make_event("experiment.recorded", {"attempt_id": aid, "model": "M", "worker": "w", "task_class": "glue",
                                             "decision": "candidate", "elapsed_s": 1}, item_id=item),
          make_event("decision.recorded", {"attempt_id": aid, "decision": "candidate", "reasons": [],
                                           "rules_revision": "v", "by": "gates"}, item_id=item)]
    commits = []
    for i, cls in enumerate(cls_fixes):
        commits.append(f"{item}{i}")
        ev.append(make_event("integrator.fix", {"attempt_id": aid, "commit": f"{item}{i}", "fix_class": cls}))
    ev.append(make_event("item.landed", {"attempt_id": aid, "train_id": "t", "fix_commits": commits}, item_id=item))
    return ev


def test_model_precision_excludes_spec_gap_fixes():
    ev = _landed("aa", []) + _landed("bb", ["spec-gap"]) + _landed("cc", ["spec-gap", "model-error"]) \
        + _landed("dd", ["gate-gap"])
    r = build_report(ev, precision_bar=0.5, min_ruled=1)
    g = r["by_class"]["glue"]
    assert g["precision"] == 0.25
    assert g["model_precision"] == 0.5          # aa clean, bb spec-gap only; cc and dd count against
    assert r["by_model"]["M"]["model_precision"] == 0.5
    assert g["fix_classes"] == {"spec-gap": 2, "model-error": 1, "gate-gap": 1}


def test_stop_conditions_use_model_precision():
    ev = []
    for i in range(4):
        ev += _landed(f"s{i}x", ["spec-gap"])
    r = build_report(ev, precision_bar=0.5, min_ruled=4)
    assert r["by_class"]["glue"]["precision"] == 0.0
    assert r["stop_conditions"] == []            # planner errors do not retire the model's task class
    assert r["planner_flags"] == ["task_class glue: 4 of 4 ruled items needed spec-gap fixes"]
