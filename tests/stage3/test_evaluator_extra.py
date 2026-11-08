"""Extra evaluator coverage: attempt recording, backfill skips and report wiring."""
import subprocess
import textwrap
from pathlib import Path

from lanectl import evaluator
from lanectl.contracts import make_event
from lanectl.events import EventLog
from lanectl.report import build_report, format_report


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def _commit(cwd, message):
    _git(cwd, "add", "-A")
    _git(cwd, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", message)
    return _git(cwd, "rev-parse", "HEAD")


def _home(tmp_path, repo, seed, rules):
    home = tmp_path / "home"
    (home / "governance" / "lanes").mkdir(parents=True)
    lane_src = Path(__file__).parents[2] / "governance" / "lanes" / "implement.toml"
    (home / "governance" / "lanes" / "implement.toml").write_text(lane_src.read_text())
    (home / "governance" / "evaluator.toml").write_text(rules)
    (home / "governance" / "repos.toml").write_text(textwrap.dedent(f"""
        [repos.target]
        path = "{repo}"
        test_cmd = "pytest -q {{files}}"
        check_cmd = "pytest -q"
        worktree_root = "{tmp_path / 'wt'}"
        """))
    rel = home / "backlog" / "item"
    rel.mkdir(parents=True)
    (rel / "release.toml").write_text(textwrap.dedent(f"""
        id = "item"
        repo = "target"
        base_sha = "{seed}"
        title = "item"
        outcome = "do it"
        task_class = "glue"
        size = "M"
        data_class = "public"
        [scope]
        paths = ["src/**", "tests/**"]
        """))
    return home


def _attempt_events(seed, head, aid="item-a1"):
    item = aid.rsplit("-a", 1)[0]
    return [make_event("item.claimed", {"attempt_id": aid, "lane": "implement",
                                        "model": "M", "worker": "opencode"}, item_id=item),
            make_event("attempt.finished", {"attempt_id": aid, "outcome": "done",
                                            "exit_code": 0, "head_sha": head,
                                            "seed_sha": seed}, item_id=item),
            make_event("decision.recorded", {"attempt_id": aid, "decision": "candidate",
                                             "reasons": [], "rules_revision": "decision-rules/v3",
                                             "by": "gates"}, item_id=item)]


def _append(log, events):
    for e in events:
        log.append(e["type"], e["data"], item_id=e["item_id"])


def test_evaluate_attempt_records_once_and_backfill_skips_missing_branch(
        tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "x.py").write_text("a = 1\n")
    _git(repo, "init", "-q", "-b", "main")
    seed = _commit(repo, "seed")
    (repo / "src" / "x.py").write_text("a = 2\nb = 3\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n")
    head = _commit(repo, "work")
    _git(repo, "branch", "lane/item-a1", head)

    rules = (f"revision = 4\ndefault = \"accept\"\n\n"
             f"[[rules]]\nname = \"sprawl\"\nfeature = \"files_touched\"\n"
             f"op = \">=\"\nvalue = 1\nverdict = \"reject\"\n")
    monkeypatch.setenv("LANECTL_HOME", str(_home(tmp_path, repo, seed, rules)))
    monkeypatch.setenv("LANECTL_STATE", str(tmp_path / "state"))
    log = EventLog()

    _append(log, _attempt_events(seed, head))
    # A second gate-accepted attempt whose lane branch was never fetched.
    _append(log, _attempt_events(seed, head, aid="other-a1"))
    data = evaluator.evaluate_attempt(log, "item-a1")
    assert data["verdict"] == "reject" and data["reasons"] == ["sprawl"]
    assert data["evaluator"] == "rules" and data["rules_revision"] == "evaluator/v4"
    assert data["features"] == {"changed_lines": 5, "changed_lines_ratio": 5 / 700,
                                "new_test_files": 1, "files_touched": 2}
    assert evaluator.evaluate_attempt(log, "item-a1") == data
    recorded = [e for e in log.read() if e["type"] == "evaluation.recorded"]
    assert len(recorded) == 1

    assert evaluator.backfill(log) == [
        "other-a1: skipped (lane branch lane/other-a1 missing)"]
    assert len([e for e in log.read() if e["type"] == "evaluation.recorded"]) == 1

    from lanectl import cli
    assert cli.main(["evaluate", "--backfill"]) == 0
    assert "lane/other-a1 missing" in capsys.readouterr().out


def test_evaluate_ops_and_feature_guards():
    rules = {"revision": 1, "default": "accept", "rules": [
        {"name": "low", "feature": "n", "op": "<=", "value": 1, "verdict": "reject"},
        {"name": "high", "feature": "n", "op": ">=", "value": 5, "verdict": "reject"},
        {"name": "unknown-feature", "feature": "missing", "op": "==",
         "value": 0, "verdict": "reject"}]}
    assert evaluator.evaluate({"n": 1}, rules) == ("reject", ["low"])
    assert evaluator.evaluate({"n": 5}, rules) == ("reject", ["high"])
    assert evaluator.evaluate({"n": 3}, rules) == ("accept", [])


def test_report_carries_evaluator_agreement_and_prints_it():
    aid = "aa-a1"
    ev = [make_event("experiment.recorded", {"attempt_id": aid, "model": "M", "worker": "w",
                                             "task_class": "glue", "decision": "candidate",
                                             "elapsed_s": 1.0}, item_id="aa"),
          make_event("evaluation.recorded", {"attempt_id": aid, "evaluator": "rules",
                                             "verdict": "accept", "rules_revision": "evaluator/v1",
                                             "features": {}, "reasons": []}, item_id="aa"),
          make_event("item.landed", {"attempt_id": aid, "train_id": "t",
                                     "fix_commits": []}, item_id="aa")]
    report = build_report(ev)
    assert report["evaluator"] == {"glue": {"evaluated_ruled": 1, "agreed": 1,
                                            "agreement": 1.0}}
    text = format_report(report)
    assert "evaluator:" in text and "glue:" in text and "agreement=1.000" in text
