"""ready reports in-flight item states (implemented, gated, candidate, in-train) instead of READY."""
from lanectl import cli
from lanectl.events import EventLog

ACC = "def test_ok():\n    assert True\n"
CLAIM = {"lane": "implement", "model": "scripted/model", "worker": "scripted"}
FINISH = {"outcome": "done", "exit_code": 0, "head_sha": "0" * 40}


def _label(out, item):
    (line,) = [ln for ln in out.splitlines() if ln.split()[-1:] == [item]]
    return line.split()[0]


def _publish(log: EventLog, item: str) -> None:
    log.append("release.published", {"release_id": item, "revision": 1}, item_id=item)


def _claim(log: EventLog, item: str, attempt: str) -> None:
    log.append("item.claimed", dict(CLAIM, attempt_id=attempt), item_id=item)


def test_states_padded_and_reasonless(estate, capsys):
    _, release, log = estate
    for item in ("aa-implemented", "bb-gated", "cc-candidate", "dd-train", "ee-ready"):
        release(item, ACC)
        _publish(log, item)

    _claim(log, "aa-implemented", "aa-implemented-a1")
    log.append("attempt.finished", dict(FINISH, attempt_id="aa-implemented-a1"), item_id="aa-implemented")

    _claim(log, "bb-gated", "bb-gated-a1")
    log.append("gate.result", {"attempt_id": "bb-gated-a1", "gate": "tests", "passed": True,
                               "violations": []}, item_id="bb-gated")

    _claim(log, "cc-candidate", "cc-candidate-a1")
    log.append("decision.recorded", {"attempt_id": "cc-candidate-a1", "decision": "candidate",
                                     "reasons": [], "rules_revision": "r1"}, item_id="cc-candidate")

    _claim(log, "dd-train", "dd-train-a1")
    log.append("decision.recorded", {"attempt_id": "dd-train-a1", "decision": "candidate",
                                     "reasons": [], "rules_revision": "r1"}, item_id="dd-train")
    log.append("train.built", {"train_id": "t1", "base_sha": "0" * 40,
                               "attempts": ["dd-train-a1"], "passed": True})

    assert cli.main(["ready"]) == 0
    out = capsys.readouterr().out
    assert _label(out, "aa-implemented") == "IMPLEMENTED"
    assert _label(out, "bb-gated") == "GATED"
    assert _label(out, "cc-candidate") == "CANDIDATE"
    assert _label(out, "dd-train") == "IN-TRAIN"
    assert _label(out, "ee-ready") == "READY"
    assert "    - " not in out  # in-flight states carry no readiness reasons
    for label, item in (("IMPLEMENTED", "aa-implemented"), ("GATED", "bb-gated"),
                        ("CANDIDATE", "cc-candidate"), ("IN-TRAIN", "dd-train"),
                        ("READY", "ee-ready")):
        assert f"{label:<8} {item}" in out  # label padded to 8 characters like the rest


def test_landed_still_hidden_unless_all(estate, capsys):
    _, release, log = estate
    release("aa-landed", ACC)
    _publish(log, "aa-landed")
    _claim(log, "aa-landed", "aa-landed-a1")
    log.append("item.landed", {"attempt_id": "aa-landed-a1", "train_id": "t1",
                               "fix_commits": []}, item_id="aa-landed")
    release("bb-claimed", ACC)
    _publish(log, "bb-claimed")
    _claim(log, "bb-claimed", "bb-claimed-a1")
    assert cli.main(["ready"]) == 0
    out = capsys.readouterr().out
    assert "aa-landed" not in out
    assert _label(out, "bb-claimed") == "CLAIMED"
    assert cli.main(["ready", "--all"]) == 0
    out = capsys.readouterr().out
    assert _label(out, "aa-landed") == "LANDED"
    assert _label(out, "bb-claimed") == "CLAIMED"
