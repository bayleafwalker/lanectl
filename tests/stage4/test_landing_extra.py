"""Extra coverage for shadow landing plans: ordering, latest records and CLI."""
import json

from lanectl import cli
from lanectl.contracts import make_event
from lanectl.events import EventLog
from lanectl.landing import fix_budget, plan_landing, plan_match
from lanectl.report import build_report, format_report

AUTH = {"revision": 1, "autonomous_classes": [], "fix_budget_lines": 30,
        "allowed_fix_classes": ["spec-gap", "gate-gap"]}


def evaluation(aid, verdict):
    return make_event("evaluation.recorded", {"attempt_id": aid, "evaluator": "rules",
                                              "verdict": verdict, "rules_revision": "v1"})


def train(tid, attempts, passed=True, excluded=()):
    return make_event("train.built", {"train_id": tid, "base_sha": "a" * 40,
                                      "attempts": list(attempts), "passed": passed,
                                      "excluded": [{"attempt_id": a, "reason": "x"}
                                                   for a in excluded]})


def planned(tid, plan, by="integrator-shadow"):
    return make_event("landing.planned", {"train_id": tid, "plan": plan, "by": by})


def landed(aid, tid):
    return make_event("item.landed", {"attempt_id": aid, "train_id": tid,
                                      "fix_commits": []})


def test_latest_evaluation_and_latest_train_win():
    ev = [evaluation("aa-a1", "reject"), evaluation("aa-a1", "accept"),
          train("train-1", ["aa-a1"], passed=False),
          train("train-1", ["aa-a1", "bb-a1"], passed=True,
                excluded=["cc-a1"])]
    assert plan_landing(ev, "train-1", AUTH) == [
        {"attempt_id": "aa-a1", "action": "land"},
        {"attempt_id": "bb-a1", "action": "hold"},
        {"attempt_id": "cc-a1", "action": "reject"}]


def test_model_error_breaks_a_match_and_operator_plans_are_ignored():
    plan = [{"attempt_id": "aa-a1", "action": "land"}]
    clean = [train("train-1", ["aa-a1"]), planned("train-1", plan), landed("aa-a1", "train-1")]
    assert plan_match(clean) == {"trains": 1, "matched": 1, "agreement": 1.0}
    fix = make_event("integrator.fix", {"attempt_id": "aa-a1", "commit": "c" * 40,
                                        "fix_class": "model-error"})
    assert plan_match(clean + [fix])["matched"] == 0
    operator = [train("train-1", ["aa-a1"]),
                planned("train-1", plan, by="operator"), landed("aa-a1", "train-1")]
    assert plan_match(operator) == {"trains": 0, "matched": 0, "agreement": None}


def test_fix_budget_boundary_and_allowed_class():
    ev = [make_event("integrator.fix", {"attempt_id": "aa-a1", "commit": "1" * 40,
                                        "fix_class": "spec-gap"}),
          make_event("integrator.fix", {"attempt_id": "bb-a1", "commit": "2" * 40,
                                        "fix_class": "spec-gap"})]
    assert fix_budget(ev, AUTH, {"1" * 40: 30, "2" * 40: 31}) == [
        f"bb-a1: fix {'2' * 40} touches 31 lines, over the 30-line budget"]


def test_report_and_cli_record_the_shadow_plan(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LANECTL_STATE", str(tmp_path))
    log = EventLog()
    for ev in [evaluation("aa-a1", "accept"), train("train-1", ["aa-a1"])]:
        log.append(ev["type"], ev["data"], item_id=ev["item_id"])
    assert cli.main(["plan-landing", "train-1", "--record"]) == 0
    assert "aa-a1 land" in capsys.readouterr().out

    events = log.read()
    recorded = [e for e in events if e["type"] == "landing.planned"]
    assert recorded == [{"schema": events[0]["schema"], "ts": recorded[0]["ts"],
                         "type": "landing.planned", "item_id": None,
                         "data": {"train_id": "train-1",
                                  "plan": [{"attempt_id": "aa-a1", "action": "land"}],
                                  "by": "integrator-shadow"}}]
    report = build_report(events, min_ruled=1)
    assert "landing_shadow: trains=0 matched=0 agreement=-" in format_report(report)
    assert json.dumps(report, sort_keys=True)          # JSON-safe projection
