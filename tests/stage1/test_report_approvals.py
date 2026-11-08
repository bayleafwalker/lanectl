"""Integrator fix: `lanectl approve` (integrator decision candidate) is not a rejection."""
from lanectl.contracts import make_event
from lanectl.report import build_report


def test_approval_does_not_count_as_ruled_rejection():
    ev = [make_event("experiment.recorded", {"attempt_id": "aa-a1", "model": "m", "worker": "w",
                                             "task_class": "c", "decision": "candidate", "elapsed_s": 1}, item_id="aa"),
          make_event("decision.recorded", {"attempt_id": "aa-a1", "decision": "candidate", "reasons": [],
                                           "rules_revision": "v", "by": "gates"}, item_id="aa"),
          make_event("decision.recorded", {"attempt_id": "aa-a1", "decision": "candidate", "reasons": ["ok"],
                                           "rules_revision": "integrator", "by": "integrator"}, item_id="aa")]
    assert build_report(ev)["by_class"]["c"]["ruled"] == 0
