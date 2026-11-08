"""Acceptance: learning projection (planner-owned)."""

from lanectl.contracts import make_event


def experiment(aid, cls="glue", size="S", model="opencode-go/deepseek-v4.1-flash", decision="candidate"):
    return make_event("experiment.recorded", {"attempt_id": aid, "decision": decision, "elapsed_s": 1.0,
                                              "gates_failed": [], "lane_revision": 2, "model": model,
                                              "rules_revision": "decision-rules/v3", "size": size,
                                              "task_class": cls, "worker": "opencode"},
                      item_id=aid.rsplit("-a", 1)[0])


def gates_candidate(aid):
    return make_event("decision.recorded", {"attempt_id": aid, "by": "gates", "decision": "candidate",
                                            "reasons": [], "rules_revision": "decision-rules/v3"},
                      item_id=aid.rsplit("-a", 1)[0])


def evaluation(aid, verdict):
    return make_event("evaluation.recorded", {"attempt_id": aid, "evaluator": "rules", "verdict": verdict,
                                              "rules_revision": "evaluator/v1", "features": {}, "reasons": []},
                      item_id=aid.rsplit("-a", 1)[0])


def train(tid, attempts, passed=True, excluded=(), check_tail="", ts="2026-11-08T12:00:00Z"):
    e = make_event("train.built", {"attempts": list(attempts), "base_sha": "a" * 40, "check_tail": check_tail,
                                   "excluded": [{"attempt_id": a, "reason": "merge conflict"} for a in excluded],
                                   "passed": passed, "repo": "lanectl", "train_id": tid,
                                   "worktree": f"/w/{tid}"})
    e["ts"] = ts
    return e


def landed(aid, tid, fixes=()):
    return make_event("item.landed", {"attempt_id": aid, "train_id": tid, "fix_commits": list(fixes)},
                      item_id=aid.rsplit("-a", 1)[0])

from lanectl.learning import load_limits, posterior, suggest

LIMITS = {"revision": 1, "min_weight": 0.05, "max_weight": 1.0, "min_evidence": 2, "prior": [1, 1]}


def _ruled(aid, model, cls="glue", fix=None):
    ev = [experiment(aid, cls=cls, model=model), gates_candidate(aid)]
    if fix:
        ev.append(make_event("integrator.fix", {"attempt_id": aid, "commit": "f" * 40, "fix_class": fix}))
    ev.append(landed(aid, "train-1", ["f" * 40] if fix else []))
    return ev


EV = (_ruled("aa-a1", "A") + _ruled("bb-a1", "A") + _ruled("cc-a1", "A", fix="model-error")
      + _ruled("dd-a1", "B", fix="model-error") + _ruled("ee-a1", "B", fix="model-error")
      + _ruled("ff-a1", "C", fix="spec-gap"))


def test_posterior_counts_model_clean():
    p = posterior(EV, LIMITS)
    assert p[("A", "glue")] == {"ruled": 3, "clean": 2, "mean": 0.6}
    assert p[("B", "glue")] == {"ruled": 2, "clean": 0, "mean": 0.25}
    assert p[("C", "glue")] == {"ruled": 1, "clean": 1, "mean": round(2 / 3, 3)}


def test_suggest_scales_clamps_and_respects_min_evidence():
    w = suggest(EV, LIMITS, ["A", "B", "C", "D"], "glue")
    # A 0.6, B 0.25, C below min_evidence -> prior 0.5, D unseen -> prior 0.5; scaled by 1/0.6
    assert w == {"A": 1.0, "B": round(0.25 / 0.6, 3), "C": round(0.5 / 0.6, 3), "D": round(0.5 / 0.6, 3)}
    # B: 0 clean of 2 -> 0.25, scaled 0.25/0.75 = 0.333 -> clamped up to min_weight 0.4
    lim = {**LIMITS, "min_weight": 0.4}
    low = suggest(_ruled("aa-a1", "A") + _ruled("bb-a1", "A") + _ruled("dd-a1", "B", fix="model-error")
                  + _ruled("ee-a1", "B", fix="model-error"), lim, ["A", "B"], "glue")
    assert low == {"A": 1.0, "B": 0.4}


def test_repo_limits_load():
    lim = load_limits()
    assert 0 < lim["min_weight"] <= lim["max_weight"] and len(lim["prior"]) == 2
