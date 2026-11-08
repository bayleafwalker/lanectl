"""Unit: posterior evidence, suggestion bounds and the ``lanectl learn`` plugin."""
from lanectl import cli
from lanectl.contracts import make_event
from lanectl.learning import load_limits, posterior, suggest

LIMITS = {"revision": 1, "min_weight": 0.05, "max_weight": 1.0,
          "min_evidence": 5, "prior": [1, 1]}


def _attempt(aid, model, cls="glue", fix=None, spec_gap=False, rejected=False):
    item = aid.rsplit("-a", 1)[0]
    events = [
        make_event("experiment.recorded",
                   {"attempt_id": aid, "decision": "candidate", "elapsed_s": 1.0,
                    "gates_failed": [], "lane_revision": 2, "model": model,
                    "rules_revision": "decision-rules/v3", "size": "S",
                    "task_class": cls, "worker": "opencode"}, item_id=item),
    ]
    if rejected:
        events.append(make_event("decision.recorded",
                                 {"attempt_id": aid, "by": "gates",
                                  "decision": "candidate", "reasons": [],
                                  "rules_revision": "decision-rules/v3"}, item_id=item))
        events.append(make_event("decision.recorded",
                                 {"attempt_id": aid, "by": "integrator",
                                  "decision": "rejected", "reasons": ["bad"],
                                  "rules_revision": "decision-rules/v3"}, item_id=item))
    else:
        events.append(make_event("decision.recorded",
                                 {"attempt_id": aid, "by": "gates",
                                  "decision": "candidate", "reasons": [],
                                  "rules_revision": "decision-rules/v3"}, item_id=item))
        if fix:
            events.append(make_event("integrator.fix",
                                     {"attempt_id": aid, "commit": "f" * 40,
                                      "fix_class": fix}))
        events.append(make_event("item.landed",
                                 {"attempt_id": aid, "train_id": "train-1",
                                  "fix_commits": ["f" * 40] if fix else []}, item_id=item))
    return events


def _log(*attempts):
    events = []
    for attempt in attempts:
        events += attempt
    return events


def test_integrator_rejected_attempt_is_ruled_but_never_clean():
    events = _log(_attempt("aa-a1", "A", rejected=True))
    view = posterior(events, {**LIMITS, "min_evidence": 1})
    assert view[("A", "glue")] == {"ruled": 1, "clean": 0, "mean": round(1 / 3, 3)}


def test_spec_gap_fix_stays_model_clean_but_model_error_does_not():
    events = _log(_attempt("aa-a1", "A", fix="spec-gap"),
                  _attempt("bb-a1", "B", fix="model-error"))
    view = posterior(events, {**LIMITS, "min_evidence": 1})
    assert view[("A", "glue")] == {"ruled": 1, "clean": 1, "mean": round(2 / 3, 3)}
    assert view[("B", "glue")] == {"ruled": 1, "clean": 0, "mean": round(1 / 3, 3)}


def test_min_evidence_boundary_uses_posterior_at_the_threshold():
    events = _log(*(_attempt(f"{n:02d}-a1", "A") for n in range(5)))
    limits = {**LIMITS, "min_evidence": 5}
    # five clean rulings is exactly enough evidence: mean (1+5)/(2+5)
    assert suggest(events, limits, ["A", "B"], "glue") == {
        "A": 1.0, "B": round((1 / 2) / (6 / 7), 3)}
    limits = {**LIMITS, "min_evidence": 6}
    assert suggest(events, limits, ["A", "B"], "glue") == {"A": 1.0, "B": 1.0}


def test_weights_scale_to_max_weight_then_clamp_to_min_weight():
    events = _log(_attempt("aa-a1", "A"), _attempt("bb-a1", "A"),
                  _attempt("cc-a1", "B", fix="model-error"),
                  _attempt("dd-a1", "B", fix="model-error"))
    limits = {**LIMITS, "min_evidence": 2, "max_weight": 2.0, "min_weight": 0.3}
    w = suggest(events, limits, ["A", "B", "Z"], "glue")
    # A 0.75 -> 2.0, B 0.25 -> 0.666, Z prior 0.5 -> 1.333
    assert w == {"A": 2.0, "B": 0.667, "Z": 1.333}
    limits = {**limits, "min_weight": 0.8}
    assert suggest(events, limits, ["A", "B"], "glue") == {"A": 2.0, "B": 0.8}


def test_suggest_only_uses_the_requested_task_class():
    events = _log(_attempt("aa-a1", "A", cls="docs"),
                  _attempt("bb-a1", "A", cls="docs"))
    assert suggest(events, {**LIMITS, "min_evidence": 2}, ["A"], "glue") == {"A": 1.0}
    codes = suggest(events, {**LIMITS, "min_evidence": 2}, ["A"], "docs")
    assert codes == {"A": 1.0}


def test_load_limits_reads_a_named_file(tmp_path):
    path = tmp_path / "routing.toml"
    path.write_text('revision = 7\nmin_weight = 0.1\nmax_weight = 0.9\n'
                    'min_evidence = 3\nprior = [2, 5]\n')
    assert load_limits(path) == {"revision": 7, "min_weight": 0.1, "max_weight": 0.9,
                                 "min_evidence": 3, "prior": [2.0, 5.0]}


def test_learn_command_prints_posterior_and_lane_weights(tmp_path, capsys, monkeypatch):
    import json
    with (tmp_path / "events.jsonl").open("a") as fh:
        for event in _log(_attempt("aa-a1", "opencode-go/deepseek-v4.1-flash")):
            fh.write(json.dumps(event) + "\n")
    monkeypatch.setenv("LANECTL_STATE", str(tmp_path))
    assert cli.main(["learn"]) == 0
    out = capsys.readouterr().out
    assert "glue" in out
    assert "current=" in out and "suggested=" in out
