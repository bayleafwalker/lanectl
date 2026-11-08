"""Acceptance: per-class / per-model report with stop-condition flags (planner-owned)."""
from lanectl.contracts import make_event
from lanectl.report import build_report


def _attempt(item, n, model, tclass, decision, elapsed, landed=None, fixes=0, by_integrator=None):
    aid = f"{item}-a{n}"
    ev = [make_event("item.claimed", {"attempt_id": aid, "lane": "implement", "model": model, "worker": "w"}, item_id=item),
          make_event("decision.recorded", {"attempt_id": aid, "decision": decision, "reasons": [],
                                           "rules_revision": "v1", "by": "gates"}, item_id=item),
          make_event("experiment.recorded", {"attempt_id": aid, "model": model, "worker": "w", "task_class": tclass,
                                             "decision": decision, "elapsed_s": elapsed}, item_id=item)]
    if landed:
        for i in range(fixes):
            ev.append(make_event("integrator.fix", {"attempt_id": aid, "commit": f"c{i}", "fix_class": "model-error"}))
        ev.append(make_event("item.landed", {"attempt_id": aid, "train_id": "t", "fix_commits": [f"c{i}" for i in range(fixes)]}, item_id=item))
    if by_integrator:
        ev.append(make_event("decision.recorded", {"attempt_id": aid, "decision": "rejected", "reasons": ["x"],
                                                   "rules_revision": "integrator", "by": "integrator"}, item_id=item))
    return ev


def test_report_groups_and_flags():
    ev = [make_event("usage.recorded", {"provider": "opencode", "source": "adapter", "attempt_id": "aa-a1",
                                        "model": "M1", "units": {"input_tokens": 100, "output_tokens": 10}}, item_id="aa")]
    ev += _attempt("aa", 1, "M1", "glue", "candidate", 100, landed=True)
    ev += _attempt("bb", 1, "M1", "glue", "candidate", 50, landed=True, fixes=2)
    ev += _attempt("cc", 1, "M1", "glue", "rejected", 30)
    ev += _attempt("dd", 1, "M2", "glue", "candidate", 20, by_integrator=True)
    ev += _attempt("ee", 1, "M2", "semantic", "parked", 10)

    r = build_report(ev, precision_bar=0.5, min_ruled=2)
    g = r["by_class"]["glue"]
    assert g["attempts"] == 4 and g["gate_accepted"] == 3 and g["ruled"] == 3
    assert g["landed_clean"] == 1 and g["precision"] == round(1 / 3, 3)
    assert g["below_bar"] is True
    assert r["by_class"]["semantic"]["ruled"] == 0 and r["by_class"]["semantic"]["below_bar"] is False
    m1 = r["by_model"]["M1"]
    assert m1["attempts"] == 3 and m1["mean_elapsed_s"] == 60.0
    assert m1["usage"] == {"input_tokens": 100, "output_tokens": 10}
    assert r["fix_classes"] == {"model-error": 2}
    assert r["stop_conditions"] == ["task_class glue: precision 0.333 < 0.5 over 3 ruled items"]


def test_report_cli_json(capsys, tmp_path, monkeypatch):
    import json
    from lanectl import cli
    from lanectl.events import EventLog
    monkeypatch.setenv("LANECTL_STATE", str(tmp_path))
    log = EventLog()
    for e in _attempt("aa", 1, "M1", "glue", "candidate", 10, landed=True):
        log.append(e["type"], e["data"], item_id=e["item_id"])
    assert cli.main(["report", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["by_class"]["glue"]["precision"] == 1.0
