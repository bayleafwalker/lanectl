"""Reservations and usage dedup: edges beyond the planner acceptance file.

The ``estate`` fixture comes from tests/stage7/conftest.py.
"""
import os
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lanectl import capacity, runner
from lanectl.adapters import AdapterResult
from lanectl.contracts import make_event
from lanectl.reap import reap
from tests.seed.test_end_to_end import SUB_TEST

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
LATER = datetime.now(timezone.utc) + timedelta(days=1)


def _policy_home():
    gov = Path(os.environ["LANECTL_HOME"]) / "governance"
    gov.mkdir(parents=True, exist_ok=True)
    (gov / "allocation.toml").write_text(textwrap.dedent("""
        revision = 9
        [providers.scripted]
        unit = "output_tokens"
        expiring = true
        pool = "scripted:test"
        [[providers.scripted.windows]]
        name = "5h"
        length_s = 18000
        budget = 1000000
        [providers.scripted.estimates]
        S = 15000
        """))


def _pol():
    return capacity.AllocationPolicy.from_dict({"revision": 1, "providers": {"opencode": {
        "unit": "output_tokens", "expiring": True, "pool": "p:1", "freshness_s": 3600,
        "windows": [{"name": "5h", "length_s": 18000, "budget": 100000}],
        "estimates": {"S": 1000}}}})


def _reserved(rid, provider="opencode", pool="p:1", amount=1000):
    return make_event("capacity.reserved", {"reservation_id": rid, "provider": provider,
                      "pool": pool, "unit": "output_tokens", "amount": amount,
                      "attempt_id": rid.removeprefix("res-")})


def _reconciled(rid, actual=None, outcome="completed"):
    return make_event("capacity.reconciled", {"reservation_id": rid, "actual": actual,
                                              "outcome": outcome})


def _usage(source, n, attempt_id=None, ts="2026-11-09T11:30:00Z"):
    data = {"provider": "opencode", "source": source, "units": {"output_tokens": n}}
    if attempt_id:
        data["attempt_id"] = attempt_id
    return make_event("usage.recorded", data, ts=ts)


def _of(log, etype):
    return [e["data"] for e in log.read() if e["type"] == etype]


# ---------------------------------------------------------------- ledger folds

def test_in_flight_sums_open_reservations_per_provider_and_pool():
    ev = [_reserved("res-aa-a1", amount=1000), _reserved("res-bb-a1", amount=2500),
          _reserved("res-cc-a1", provider="codex", amount=999),
          _reserved("res-dd-a1", pool="p:2", amount=400), _reconciled("res-aa-a1", actual=10)]
    assert capacity.in_flight(ev, "opencode", "p:1") == 2500   # res-aa-a1 is closed
    assert capacity.in_flight(ev, "codex", "p:1") == 999
    assert capacity.in_flight(ev, "opencode", "p:2") == 400


def test_usage_counts_overlapping_sources_once_but_increments_sum():
    ev = [_usage("adapter", 4000, "aa-a1"),
          _usage("hook", 4500, "aa-a1", ts="2026-11-09T11:31:00Z"),
          _usage("adapter", 100, ts="2026-11-09T11:32:00Z")]
    used = capacity.project(ev, _pol(), NOW)["opencode"]["5h"]["used"]
    # the adapter and the hook both report attempt aa-a1: the later row wins;
    # the unattributed adapter row is its own observation.
    assert used == 4500 + 100


# ---------------------------------------------------------------- admission view

def test_in_flight_is_visible_but_never_makes_unknown_capacity_free():
    rsv = _reserved("res-aa-a1", amount=7000)
    v = capacity.qualified([rsv], _pol(), NOW)["opencode"]
    assert v["basis"] == "unknown" and v["in_flight"] == 7000
    a = capacity.capacity_admission([rsv], _pol(), NOW, "opencode", "S")
    assert a["basis"] == "unknown" and a["burnable"] is None


def test_unqualified_admission_holds_in_flight_reservations():
    legacy = capacity.AllocationPolicy.from_dict({"revision": 3, "providers": {"p": {
        "unit": "output_tokens", "expiring": True,
        "windows": [{"name": "5h", "length_s": 18000, "budget": 50000}],
        "estimates": {"S": 1}}}})
    rsv = make_event("capacity.reserved", {"reservation_id": "res-aa-a1", "provider": "p",
                     "pool": "p:default", "unit": "output_tokens", "amount": 2000,
                     "attempt_id": "aa-a1"})
    assert capacity.capacity_admission([], legacy, NOW, "p", "S")["burnable"] == 50000
    a = capacity.capacity_admission([rsv], legacy, NOW, "p", "S")
    assert a["burnable"] == 48000 and any("in-flight" in r for r in a["reasons"])


# ---------------------------------------------------------------- runner / reaper

def test_completion_without_adapter_usage_reconciles_none_once(estate):
    repo, release, log = estate
    _policy_home()
    release("add-sub", SUB_TEST)
    c = runner.admit("implement", log)
    assert len(_of(log, "capacity.reserved")) == 1
    runner.execute(c, log, adapter_fn=lambda **_: AdapterResult("failed", 1, "noop", None))
    assert _of(log, "capacity.reconciled") == [
        {"reservation_id": f"res-{c.attempt_id}", "actual": None, "outcome": "completed"}]
    # a closed reservation is never reconciled twice
    assert runner.reconcile_capacity(log, log.read(), c.attempt_id, actual=1,
                                     outcome="recovered") is False
    assert len(_of(log, "capacity.reconciled")) == 1


def test_reap_recovers_finished_attempt_reservation(estate):
    repo, release, log = estate
    _policy_home()
    release("add-sub", SUB_TEST)
    c = runner.admit("implement", log)
    assert len(_of(log, "capacity.reserved")) == 1
    log.append("attempt.finished", {"attempt_id": c.attempt_id, "outcome": "failed",
               "exit_code": 1, "head_sha": "", "elapsed_s": 0.0}, item_id="add-sub")
    log.append("gate.result", {"attempt_id": c.attempt_id, "gate": "acceptance",
               "passed": False, "violations": ["boom"]}, item_id="add-sub")
    assert reap(log, now=LATER, older_than_s=60, max_attempts=2) == [c.attempt_id]
    assert _of(log, "capacity.reconciled") == [
        {"reservation_id": f"res-{c.attempt_id}", "actual": None, "outcome": "recovered"}]
    assert capacity.in_flight(log.read(), "scripted", "scripted:test") == 0
    # recovered once, not again on the next reap
    assert reap(log, now=LATER, older_than_s=60, max_attempts=2) == []
    assert len(_of(log, "capacity.reconciled")) == 1
