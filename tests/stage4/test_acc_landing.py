"""Acceptance: shadow landing plans (planner-owned)."""

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

from lanectl.landing import fix_budget, load_authority, plan_landing, plan_match
from lanectl.report import build_report

AUTH = {"revision": 1, "autonomous_classes": [], "fix_budget_lines": 30,
        "allowed_fix_classes": ["spec-gap", "gate-gap"]}


def _base():
    return [experiment("aa-a1"), gates_candidate("aa-a1"), evaluation("aa-a1", "accept"),
            experiment("bb-a1"), gates_candidate("bb-a1"), evaluation("bb-a1", "reject"),
            experiment("cc-a1"), gates_candidate("cc-a1"),
            train("train-1", ["aa-a1", "bb-a1", "cc-a1"], excluded=["dd-a1"])]


def test_plan_follows_evaluator_and_train():
    assert plan_landing(_base(), "train-1", AUTH) == [
        {"attempt_id": "aa-a1", "action": "land"}, {"attempt_id": "bb-a1", "action": "hold"},
        {"attempt_id": "cc-a1", "action": "hold"}, {"attempt_id": "dd-a1", "action": "reject"}]
    failed = _base()[:-1] + [train("train-1", ["aa-a1"], passed=False)]
    assert plan_landing(failed, "train-1", AUTH) == [{"attempt_id": "aa-a1", "action": "hold"}]


def _planned(plan):
    return make_event("landing.planned", {"train_id": "train-1", "plan": plan, "by": "integrator-shadow"})


def test_plan_match():
    plan = [{"attempt_id": "aa-a1", "action": "land"}, {"attempt_id": "bb-a1", "action": "hold"}]
    ok = _base() + [_planned(plan), landed("aa-a1", "train-1")]
    assert plan_match(ok) == {"trains": 1, "matched": 1, "agreement": 1.0}
    extra = _base() + [_planned(plan), landed("aa-a1", "train-1"), landed("bb-a1", "train-1")]
    assert plan_match(extra)["matched"] == 0
    assert plan_match(_base() + [_planned(plan)]) == {"trains": 0, "matched": 0, "agreement": None}
    assert build_report(ok, min_ruled=1)["landing_shadow"]["agreement"] == 1.0


def test_fix_budget_warnings():
    ev = [make_event("integrator.fix", {"attempt_id": "aa-a1", "commit": "1" * 40, "fix_class": "spec-gap"}),
          make_event("integrator.fix", {"attempt_id": "bb-a1", "commit": "2" * 40, "fix_class": "model-error"}),
          make_event("integrator.fix", {"attempt_id": "cc-a1", "commit": "3" * 40, "fix_class": "gate-gap"})]
    w = fix_budget(ev, AUTH, {"1" * 40: 10, "2" * 40: 5, "3" * 40: 31})
    assert len(w) == 2 and any("bb-a1" in x for x in w) and any("cc-a1" in x for x in w)


def test_repo_authority_loads():
    a = load_authority()
    assert a["revision"] >= 1 and isinstance(a["autonomous_classes"], list)
    assert set(a["allowed_fix_classes"]) <= {"spec-gap", "model-error", "gate-gap"}
