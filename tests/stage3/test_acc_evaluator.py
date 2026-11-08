"""Acceptance: rules evaluator and its agreement with the integrator (planner-owned)."""
import subprocess

from lanectl.contracts import make_event
from lanectl.evaluator import agreement, evaluate, features, load_rules

RULES = {"revision": 1, "default": "accept", "rules": [
    {"name": "near-size-budget", "feature": "changed_lines_ratio", "op": ">", "value": 0.8, "verdict": "reject"},
    {"name": "no-new-tests", "feature": "new_test_files", "op": "==", "value": 0, "verdict": "reject"}]}


def test_first_matching_rule_wins():
    f = {"changed_lines": 900, "changed_lines_ratio": 0.9, "new_test_files": 0, "files_touched": 3}
    assert evaluate(f, RULES) == ("reject", ["near-size-budget"])
    f.update(changed_lines_ratio=0.2)
    assert evaluate(f, RULES) == ("reject", ["no-new-tests"])
    f.update(new_test_files=1)
    assert evaluate(f, RULES) == ("accept", [])


def test_repo_rules_load():
    r = load_rules()
    assert r["revision"] >= 1 and r["default"] in ("accept", "reject")
    assert all({"name", "feature", "op", "value", "verdict"} <= set(x) for x in r["rules"])


def _git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def test_features_from_diff(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "m.py").write_text("a = 1\n")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed")
    seed = _git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "src" / "m.py").write_text("a = 2\nb = 3\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_m.py").write_text("def test_m():\n    assert True\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "work")
    head = _git(tmp_path, "rev-parse", "HEAD")
    f = features(tmp_path, seed, head, 50, ("tests/**/test_*.py", "tests/test_*.py"))
    assert f == {"changed_lines": 5, "changed_lines_ratio": 0.1, "new_test_files": 1, "files_touched": 2}


def _ruled(aid, verdict, landed=True, fix=None, cls="glue"):
    item = aid.rsplit("-a", 1)[0]
    ev = [make_event("experiment.recorded", {"attempt_id": aid, "decision": "candidate", "elapsed_s": 1.0,
                                             "gates_failed": [], "lane_revision": 2, "model": "M",
                                             "rules_revision": "decision-rules/v3", "size": "S",
                                             "task_class": cls, "worker": "opencode"}, item_id=item),
          make_event("decision.recorded", {"attempt_id": aid, "by": "gates", "decision": "candidate",
                                           "reasons": [], "rules_revision": "decision-rules/v3"}, item_id=item),
          make_event("evaluation.recorded", {"attempt_id": aid, "evaluator": "rules", "verdict": verdict,
                                             "rules_revision": "evaluator/v1", "features": {}, "reasons": []},
                     item_id=item)]
    if fix:
        ev.append(make_event("integrator.fix", {"attempt_id": aid, "commit": "f" * 40, "fix_class": fix}))
    if landed:
        ev.append(make_event("item.landed", {"attempt_id": aid, "train_id": "tt",
                                             "fix_commits": ["f" * 40] if fix else []}, item_id=item))
    else:
        ev.append(make_event("decision.recorded", {"attempt_id": aid, "by": "integrator", "decision": "rejected",
                                                   "reasons": ["no"], "rules_revision": "integrator"}, item_id=item))
    return ev


def test_agreement_per_task_class():
    ev = (_ruled("aa-a1", "accept") + _ruled("bb-a1", "accept", fix="spec-gap")
          + _ruled("cc-a1", "accept", fix="model-error") + _ruled("dd-a1", "reject", landed=False)
          + _ruled("ee-a1", "reject", cls="semantic"))
    a = agreement(ev)
    assert a["glue"] == {"evaluated_ruled": 4, "agreed": 3, "agreement": 0.75}
    assert a["semantic"] == {"evaluated_ruled": 1, "agreed": 0, "agreement": 0.0}
