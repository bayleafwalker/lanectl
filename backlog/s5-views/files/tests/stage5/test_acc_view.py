"""Acceptance: static view (planner-owned)."""

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

from datetime import datetime, timezone

from lanectl import cli
from lanectl.events import EventLog
from lanectl.view import render

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def test_render_sections_and_escaping():
    ev = [experiment("aa-a1", cls="<script>x</script>"), gates_candidate("aa-a1"), landed("aa-a1", "train-1")]
    html = render(ev, NOW)
    assert html.lstrip().lower().startswith("<!doctype html>")
    for sid in ("items", "report", "capacity", "triage"):
        assert f'id="{sid}"' in html
    assert "<script>x</script>" not in html and "&lt;script&gt;" in html
    assert "<script src" not in html and "http" not in html.split("</head>")[0]


def test_cli_writes_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LANECTL_STATE", str(tmp_path))
    log = EventLog()
    e = experiment("aa-a1")
    log.append(e["type"], e["data"], item_id=e["item_id"])
    out = tmp_path / "v.html"
    assert cli.main(["view", "--html", str(out)]) == 0
    assert out.read_text().count('id="report"') == 1 and str(out) in capsys.readouterr().out
