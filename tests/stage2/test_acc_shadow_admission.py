"""Acceptance: shadow admission from capacity (planner-owned)."""
from datetime import datetime, timezone

from lanectl import runner
from lanectl.capacity import AllocationPolicy, capacity_admission
from lanectl.contracts import make_event
from lanectl.report import build_report
from tests.seed.test_end_to_end import SUB_TEST, estate  # noqa: F401  (fixture)

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
POLICY = AllocationPolicy.from_dict({"revision": 3, "providers": {"opencode": {
    "unit": "output_tokens", "expiring": True, "reservations": {},
    "windows": [{"name": "5h", "length_s": 18000, "budget": 50000, "anchor": "2026-11-08T10:00:00Z"}],
    "estimates": {"S": 15000, "M": 40000, "L": 100000}}}})


def _attempt(aid, size, out, ts="2026-11-08T11:00:00Z"):
    item = aid.rsplit("-a", 1)[0]
    u = make_event("usage.recorded", {"attempt_id": aid, "model": "opencode-go/deepseek-v4.1-flash",
                                      "provider": "opencode", "source": "adapter",
                                      "units": {"output_tokens": out}}, item_id=item)
    x = make_event("experiment.recorded", {"attempt_id": aid, "decision": "candidate", "elapsed_s": 1.0,
                                           "gates_failed": [], "lane_revision": 2,
                                           "model": "opencode-go/deepseek-v4.1-flash",
                                           "rules_revision": "decision-rules/v3", "size": size,
                                           "task_class": "glue", "worker": "opencode"}, item_id=item)
    u["ts"] = x["ts"] = ts
    return [u, x]


def test_policy_estimate_until_evidence():
    a = capacity_admission([], POLICY, NOW, "opencode", "M")
    assert (a["decision"], a["estimate"], a["burnable"]) == ("admit", 40000, 50000)
    a = capacity_admission(_attempt("aa-a1", "M", 20000), POLICY, NOW, "opencode", "M")
    assert (a["decision"], a["estimate"], a["burnable"]) == ("block", 40000, 30000)


def test_observed_mean_replaces_placeholder_after_three_attempts():
    ev = _attempt("aa-a1", "S", 1000) + _attempt("bb-a1", "S", 2000) + _attempt("cc-a1", "S", 3000)
    a = capacity_admission(ev, POLICY, NOW, "opencode", "S")
    assert a["estimate"] == 2000 and a["decision"] == "admit"


def test_unknown_provider_admits():
    a = capacity_admission([], POLICY, NOW, "anthropic", "S")
    assert a["decision"] == "admit" and a["reasons"]


def test_admit_records_shadow_decision(estate):
    repo, release, log = estate
    release("add-sub", SUB_TEST)
    c = runner.admit("implement", log)
    assert not isinstance(c, str), c
    shadow = [e for e in log.read() if e["type"] == "admission.shadow"]
    assert len(shadow) == 1
    d = shadow[0]["data"]
    assert d["static"] == "admit" and d["release_id"] == "add-sub" and d["size"] == "S"
    assert d["agree"] == (d["capacity"] == "admit")


def test_report_summarises_agreement():
    ev = [make_event("admission.shadow", {"static": "admit", "capacity": c, "agree": c == "admit",
                                          "reasons": []}) for c in ("admit", "admit", "block")]
    s = build_report(ev, min_ruled=1)["shadow_admission"]
    assert s == {"recorded": 3, "agreed": 2, "agreement": round(2 / 3, 3)}
    assert build_report([], min_ruled=1)["shadow_admission"]["agreement"] is None
