"""Extra coverage: only model-error counts against the model.

Planner-owned spec gaps and gate-owned gate gaps leave an attempt model-clean;
the text report surfaces gate flags and status counts pending candidates.
"""
from lanectl.contracts import make_event
from lanectl.report import build_report, format_report
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
    ev.append(make_event("item.landed", {"attempt_id": aid, "train_id": "t",
                                         "fix_commits": commits}, item_id=item))
    return ev


def test_gate_gap_is_not_the_models_fault():
    ev = _landed("aa", ["gate-gap"]) + _landed("bb", ["model-error"])
    r = build_report(ev, precision_bar=0.5, min_ruled=1)
    assert r["by_class"]["glue"]["model_precision"] == 0.5
    assert r["gate_flags"] == ["task_class glue: 1 of 2 ruled items needed gate-gap fixes"]


def test_text_report_prints_gate_flags():
    out = format_report(build_report(_landed("aa", ["gate-gap"]), min_ruled=1))
    assert "gate_flags:" in out
    assert "task_class glue: 1 of 1 ruled items needed gate-gap fixes" in out


def test_status_gate_accepted_includes_unruled_candidates():
    pending = _landed("ee", [])[:2]          # gates accepted; integrator has not ruled
    m = metrics(_landed("aa", []) + pending)
    assert m["gate_accepted"] == 2 and m["ruled"] == 1
