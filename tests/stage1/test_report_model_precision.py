"""Coverage for attributing fixes: only model-error counts against the model.

Planner-rewritten 2026-11-08 when the attribution rule changed (gate-gap moved off the model)."""
from lanectl.contracts import make_event
from lanectl.report import build_report, format_report


def _attempt(item, cls, fixes, landed=True):
    aid = f"{item}-a1"
    ev = [make_event("experiment.recorded", {"attempt_id": aid, "model": "M", "worker": "w",
                                             "task_class": cls, "decision": "candidate",
                                             "elapsed_s": 1}, item_id=item),
          make_event("decision.recorded", {"attempt_id": aid, "decision": "candidate",
                                           "reasons": [], "rules_revision": "v", "by": "gates"},
                     item_id=item)]
    commits = [f"{item}{i}" for i in range(len(fixes))]
    for commit, fix_class in zip(commits, fixes):
        ev.append(make_event("integrator.fix", {"attempt_id": aid, "commit": commit,
                                                "fix_class": fix_class}))
    if landed:
        ev.append(make_event("item.landed", {"attempt_id": aid, "train_id": "t",
                                             "fix_commits": commits}, item_id=item))
    return ev


def _mixed_events():
    # glue: 4 ruled -> clean, spec-gap, spec-gap+model-error, gate-gap
    ev = _attempt("aa", "glue", [])
    ev += _attempt("bb", "glue", ["spec-gap"])
    ev += _attempt("cc", "glue", ["spec-gap", "model-error"])
    ev += _attempt("dd", "glue", ["gate-gap"])
    # semantic: one model-error only, so no planner flag there
    ev += _attempt("ee", "semantic", ["model-error"])
    return ev


def test_planner_flags_count_only_ruled_items_with_spec_gaps():
    r = build_report(_mixed_events(), precision_bar=0.5, min_ruled=1)
    assert r["planner_flags"] == [
        "task_class glue: 2 of 4 ruled items needed spec-gap fixes"]


def test_model_precision_is_reported_for_both_groupings():
    r = build_report(_mixed_events(), precision_bar=0.5, min_ruled=1)
    assert r["by_class"]["glue"]["model_precision"] == 0.75
    assert r["by_model"]["M"]["model_precision"] == 0.6


def test_unruled_group_has_null_model_precision():
    r = build_report(_attempt("aa", "glue", [], landed=False), min_ruled=1)
    g = r["by_class"]["glue"]
    assert g["ruled"] == 0
    assert g["model_precision"] is None
    assert r["planner_flags"] == []


def test_stop_conditions_and_flags_follow_model_precision():
    ev = _attempt("aa", "glue", ["spec-gap"]) + _attempt("bb", "glue", ["gate-gap"])
    r = build_report(ev, precision_bar=0.75, min_ruled=2)
    g = r["by_class"]["glue"]
    assert g["precision"] == 0.0
    assert g["model_precision"] == 1.0
    assert g["below_bar"] is False
    assert r["stop_conditions"] == []
    assert r["gate_flags"] == ["task_class glue: 1 of 2 ruled items needed gate-gap fixes"]
    assert r["planner_flags"] == [
        "task_class glue: 1 of 2 ruled items needed spec-gap fixes"]


def test_text_table_shows_mprec_column_and_planner_flags():
    out = format_report(build_report(_mixed_events(), precision_bar=0.5, min_ruled=1))
    header = out.splitlines()[0]
    assert "PREC" in header and "MPREC" in header
    assert "planner_flags:" in out
    assert "task_class glue: 2 of 4 ruled items needed spec-gap fixes" in out
