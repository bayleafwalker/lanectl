"""Extra report coverage: no-ruled groups, the min-ruled gate, and CLI text."""
import json

from lanectl import cli
from lanectl.contracts import make_event
from lanectl.events import EventLog
from lanectl.report import build_report, format_report


def _attempt(item, model, decision, elapsed, landed=False, by_integrator=False):
    aid = f"{item}-a1"
    ev = [
        make_event("item.claimed", {"attempt_id": aid, "lane": "implement",
                                    "model": model, "worker": "w"}, item_id=item),
        make_event("decision.recorded", {"attempt_id": aid, "decision": decision,
                                         "reasons": [], "rules_revision": "v1",
                                         "by": "gates"}, item_id=item),
        make_event("experiment.recorded", {"attempt_id": aid, "model": model, "worker": "w",
                                           "task_class": "glue", "decision": decision,
                                           "elapsed_s": elapsed}, item_id=item),
    ]
    if landed:
        ev.append(make_event("item.landed", {"attempt_id": aid, "train_id": "t",
                                             "fix_commits": []}, item_id=item))
    if by_integrator:
        ev.append(make_event("decision.recorded", {"attempt_id": aid, "decision": "rejected",
                                                   "reasons": ["x"], "rules_revision": "integrator",
                                                   "by": "integrator"}, item_id=item))
    return ev


def test_unruled_group_has_no_precision_and_no_flag():
    ev = _attempt("aa", "M1", "candidate", 10)          # accepted, nobody ruled on it
    r = build_report(ev, precision_bar=0.5, min_ruled=1)
    g = r["by_class"]["glue"]
    assert g["gate_accepted"] == 1
    assert g["ruled"] == 0
    assert g["precision"] is None
    assert g["below_bar"] is False
    assert r["stop_conditions"] == []


def test_min_ruled_gates_the_flag_and_usage_is_summed():
    ev = _attempt("aa", "M1", "candidate", 10, landed=True)
    ev += _attempt("bb", "M1", "candidate", 20, by_integrator=True)
    ev += [make_event("usage.recorded", {"provider": "p", "source": "adapter",
                                         "attempt_id": "aa-a1", "model": "M1",
                                         "units": {"input_tokens": 5}}),
           make_event("usage.recorded", {"provider": "p", "source": "adapter",
                                         "attempt_id": "bb-a1", "model": "M1",
                                         "units": {"input_tokens": 7, "output_tokens": 2}})]

    r = build_report(ev, precision_bar=0.5, min_ruled=2)
    g = r["by_class"]["glue"]
    assert g["ruled"] == 2 and g["landed_clean"] == 1
    assert g["precision"] == 0.5
    assert g["below_bar"] is False                # equal to the bar is not below
    assert r["by_model"]["M1"]["usage"] == {"input_tokens": 12, "output_tokens": 2}
    assert r["stop_conditions"] == []

    r = build_report(ev, precision_bar=0.75, min_ruled=2)
    assert r["by_class"]["glue"]["below_bar"] is True
    assert r["stop_conditions"] == [
        "task_class glue: precision 0.500 < 0.75 over 2 ruled items"]


def test_cli_text_table_shows_flag_and_counts(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("LANECTL_STATE", str(tmp_path))
    log = EventLog()
    for e in _attempt("aa", "M1", "candidate", 10, landed=True):
        log.append(e["type"], e["data"], item_id=e["item_id"])
    for e in _attempt("bb", "M1", "candidate", 20, by_integrator=True):
        log.append(e["type"], e["data"], item_id=e["item_id"])

    assert cli.main(["report", "--precision-bar", "0.75", "--min-ruled", "2"]) == 0
    out = capsys.readouterr().out
    assert "CLASS" in out and "MODEL" in out
    assert "below" in out
    assert "task_class glue: precision 0.500 < 0.75 over 2 ruled items" in out


def test_cli_json_carries_summary_fields(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("LANECTL_STATE", str(tmp_path))
    log = EventLog()
    for e in _attempt("aa", "M1", "candidate", 10):
        log.append(e["type"], e["data"], item_id=e["item_id"])
    assert cli.main(["report", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["precision_bar"] == 0.5 and out["min_ruled"] == 20
    assert out["by_model"]["M1"]["attempts"] == 1
    assert format_report(out).startswith("CLASS")
