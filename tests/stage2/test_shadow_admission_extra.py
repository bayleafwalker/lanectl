"""Shadow admission: policy gaps, usage evidence, cap fallbacks and reporting."""
from datetime import datetime, timezone
from pathlib import Path

from lanectl import runner
from lanectl.capacity import AllocationPolicy, capacity_admission
from lanectl.contracts import make_event
from lanectl.report import build_report, format_report
from tests.seed.test_end_to_end import SUB_TEST, estate

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
POLICY = AllocationPolicy.from_dict({"revision": 3, "providers": {"opencode": {
    "unit": "output_tokens", "expiring": True, "reservations": {},
    "windows": [{"name": "5h", "length_s": 18000, "budget": 50000,
                 "anchor": "2026-11-08T10:00:00Z"}],
    "estimates": {"S": 15000, "M": 40000, "L": 100000}}}})


def attempt_events(aid, size, *usage_rows, source="adapter", ts="2026-11-08T11:00:00Z"):
    """One experiment record plus its adapter usage rows (several per attempt allowed)."""
    item = aid.rsplit("-a", 1)[0]
    events = [make_event("experiment.recorded", {
        "attempt_id": aid, "decision": "candidate", "elapsed_s": 1.0, "gates_failed": [],
        "lane_revision": 2, "model": "opencode-go/deepseek-v4.1-flash",
        "rules_revision": "decision-rules/v3", "size": size, "task_class": "glue",
        "worker": "opencode"}, item_id=item)]
    for out in usage_rows:
        events.append(make_event("usage.recorded", {
            "attempt_id": aid, "model": "opencode-go/deepseek-v4.1-flash",
            "provider": "opencode", "source": source,
            "units": {"output_tokens": out}}, item_id=item))
    for ev in events:
        ev["ts"] = ts
    return events


def test_policy_is_missing_or_silent_about_the_provider():
    no_policy = capacity_admission([], None, NOW, "opencode", "S")
    assert no_policy["decision"] == "admit" and no_policy["estimate"] is None
    assert no_policy["reasons"]
    unknown = capacity_admission([], POLICY, NOW, "anthropic", "S")
    assert unknown["decision"] == "admit" and unknown["burnable"] is None
    assert unknown["reasons"]


def test_governance_rev3_parses_size_estimates():
    policy = AllocationPolicy.load(root=Path(__file__).parents[2])
    assert policy is not None and policy.revision == 3
    assert policy.providers["opencode"].estimates == {"S": 15000, "M": 40000, "L": 100000}


def test_observed_mean_sums_usage_rows_per_attempt():
    # 3 attempts, 10000 output tokens each; the first reports it in two rows.
    events = (attempt_events("aa-a1", "M", 3000, 7000)
              + attempt_events("bb-a1", "M", 10000)
              + attempt_events("cc-a1", "M", 10000))
    a = capacity_admission(events, POLICY, NOW, "opencode", "M")
    assert a["estimate"] == 10000
    assert a["burnable"] == 50000 - 30000
    assert a["decision"] == "admit" and a["reasons"]


def test_non_adapter_usage_never_moves_the_estimate():
    events = (attempt_events("aa-a1", "S", 1, source="reconcile")
              + attempt_events("bb-a1", "S", 1, source="reconcile")
              + attempt_events("cc-a1", "S", 1, source="reconcile"))
    a = capacity_admission(events, POLICY, NOW, "opencode", "S")
    assert a["estimate"] == 15000


def test_provider_mapping_follows_the_adapter_worker():
    assert runner.provider_for("opencode-go/deepseek-v4.1-flash") == "opencode"
    assert runner.provider_for("gpt-5") == "codex"


def test_cap_block_still_shadows_the_waiting_release(estate):
    repo, release, log = estate
    for item in ("one", "two", "three", "four"):
        release(item, SUB_TEST)
    for _ in range(3):                      # lane concurrency is 3
        assert not isinstance(runner.admit("implement", log), str)
    refused = runner.admit("implement", log)
    assert isinstance(refused, str) and refused.startswith("cap: concurrency"), refused
    shadow = [e["data"] for e in log.read() if e["type"] == "admission.shadow"]
    assert [d["static"] for d in shadow] == ["admit", "admit", "admit", "block"]
    claimed = {d["release_id"] for d in shadow if d["static"] == "admit"}
    assert shadow[-1]["release_id"] not in claimed
    assert shadow[-1]["agree"] is False      # no policy here: capacity admits


def test_text_report_carries_shadow_agreement():
    events = [make_event("admission.shadow", {"static": "admit", "capacity": c,
                                              "agree": c == "admit", "reasons": []})
              for c in ("admit", "block")]
    report = build_report(events, min_ruled=1)
    assert report["shadow_admission"] == {"recorded": 2, "agreed": 1, "agreement": 0.5}
    assert "shadow_admission: recorded=2 agreed=1 agreement=0.500" in format_report(report)
    assert "agreement=-" in format_report(build_report([], min_ruled=1))
