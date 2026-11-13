"""Coverage for lifecycle accounting (UI-08 / lanectl#2898).

Complements the planner-owned acceptance file with retries, out-of-order
timestamps, release-level and operator usage, partial/missing prices, phase
boundaries, and the CLI plugin.
"""
import json

import pytest

from lanectl.accounting import _cmd, accounting_timeline, render_timeline
from lanectl.contracts import make_event
from lanectl.events import EventLog


POLICY = {"revision": 19, "providers": {"test": {"prices": {
    "models": {"model-a": {"offpeak": {"input": 1.0, "output": 2.0}}}}}}}


def ev(kind, data, minute, item="account-work"):
    return make_event(kind, data, item_id=item, ts=f"2026-11-12T10:{minute:02d}:00Z")


def usage(source, units, *, model="model-a", item="account-work",
          attempt="account-work-a1", provider="test"):
    return ev("usage.recorded", dict(provider=provider, source=source, units=units,
                                     model=model, attempt_id=attempt), 5, item=item)


def lifecycle():
    return [ev("release.published", dict(release_id="account-work", revision=1, provenance="guarded-publish"), 0),
            ev("item.claimed", dict(attempt_id="a1", lane="implement", model="m", worker="w"), 2),
            ev("attempt.finished", dict(attempt_id="a1", outcome="done", exit_code=0, head_sha="a"), 5)]


def test_retry_waiting_is_labelled_separately_and_excluded_from_execution():
    events = lifecycle() + [
        ev("item.claimed", dict(attempt_id="a2", lane="implement", model="m", worker="w"), 10),
        ev("attempt.finished", dict(attempt_id="a2", outcome="done", exit_code=0, head_sha="b"), 12)]
    phases = accounting_timeline(events, POLICY, item_id="account-work")["phases"]
    assert phases["execution"]["seconds"] == 300               # 180 + 120, never 600
    assert phases["execution"]["waiting"]["seconds"] == 300    # 05 -> 10, labelled apart
    assert phases["execution"]["intervals"][0]["kind"] == "execution"
    assert phases["execution"]["waiting"]["intervals"][0]["kind"] == "waiting"
    # No interval joins the first claim to the last finish across retries.
    assert [iv["attempt_id"] for iv in phases["execution"]["intervals"]] == ["a1", "a2"]
    # Every duration carries its basis, not just a number.
    for phase in phases.values():
        assert all(iv["basis"] for iv in phase["intervals"])
    assert all(iv["basis"] for iv in phases["execution"]["waiting"]["intervals"])


def test_misordered_timestamps_never_yield_negative_durations():
    events = [ev("release.published", dict(release_id="account-work", revision=1, provenance="guarded-publish"), 0),
              ev("item.claimed", dict(attempt_id="a1", lane="implement", model="m", worker="w"), 5),
              ev("attempt.finished", dict(attempt_id="a1", outcome="done", exit_code=0, head_sha="a"), 2)]
    phases = accounting_timeline(events, POLICY, item_id="account-work")["phases"]
    assert phases["queued"]["seconds"] == 300
    assert phases["execution"]["seconds"] is None
    assert phases["execution"]["intervals"][0]["seconds"] is None


def test_unfinished_attempt_makes_the_aggregate_unknown_but_keeps_a_subtotal():
    events = lifecycle() + [ev("item.claimed", dict(
        attempt_id="a2", lane="implement", model="m", worker="w"), 10)]
    execution = accounting_timeline(events, POLICY, item_id="account-work")["phases"]["execution"]
    assert execution["seconds"] is None
    assert execution["known_seconds"] == 180
    assert any(iv["seconds"] is None for iv in execution["intervals"])


def test_attempt_query_excludes_release_level_and_other_attempt_usage():
    events = [usage("adapter", {"output_tokens": 10}),                   # a1
              usage("adapter", {"output_tokens": 20}, attempt="a2"),     # a2
              usage("adapter", {"output_tokens": 40}, attempt=None)]     # release-level
    release = accounting_timeline(events, POLICY, item_id="account-work")
    assert release["usage"]["lane"]["units"]["output_tokens"] == 70
    attempt = accounting_timeline(events, POLICY, item_id="account-work", attempt_id="a2")
    assert attempt["usage"]["lane"]["units"]["output_tokens"] == 20
    assert attempt["attribution"]["attributed_events"] == 1
    assert attempt["attribution"]["unattributed_events"] == 0
    assert attempt["attribution"].get("outside_scope_events") == 2


def test_operator_source_is_operator_and_unknown_units_are_preserved():
    events = [usage("adapter", {"output_tokens": 100, "mystery_units": 3}),
              usage("claude-code-interactive", {"input_tokens": 100})]
    result = accounting_timeline(events, POLICY, item_id="account-work")
    lane = result["usage"]["lane"]
    assert lane["usd_est"] is None                 # mystery_units makes it unpriced
    assert lane["units"]["mystery_units"] == 3     # raw unit retained
    assert lane["units"]["output_tokens"] == 100
    assert result["usage"]["operator"]["usd_est"] == pytest.approx(100 / 1_000_000)


def test_partial_and_missing_prices_never_report_zero_or_a_complete_total():
    events = [usage("adapter", {"output_tokens": 100}),
              usage("adapter", {"output_tokens": 50}, model="no-price")]
    lane = accounting_timeline(events, POLICY, item_id="account-work")["usage"]["lane"]
    assert lane["usd_est"] is None
    assert lane["known_usd_est"] == pytest.approx(100 * 2.0 / 1_000_000)
    assert lane["priced_events"] == 1 and lane["unpriced_events"] == 1

    # One priced column does not prove the whole event priced.
    mixed = accounting_timeline([usage("adapter", {"input_tokens": 100, "output_tokens": 50})],
                                {"revision": 1, "providers": {"test": {"prices": {
                                    "models": {"model-a": {"offpeak": {"input": 1.0}}}}}}},
                                item_id="account-work")["usage"]["lane"]
    assert mixed["usd_est"] is None and mixed["unpriced_events"] == 1


def test_empty_or_nonnumeric_units_are_unpriced_not_zero_dollars():
    for units in ({}, {"output_tokens": "unknown"}, {"output_tokens": None}):
        lane = accounting_timeline([usage("adapter", units)], POLICY,
                                   item_id="account-work")["usage"]["lane"]
        assert lane["usd_est"] is None
        assert lane["unpriced_events"] == 1


def test_attempt_query_does_not_borrow_landing_or_verification():
    events = lifecycle() + [
        ev("item.landed", dict(attempt_id="a1", train_id="tr-1", fix_commits=[]), 8),
        ev("work.synced", dict(work="lanectl#2898", train_id="tr-1", closed=True, ok=True), 9)]
    release = accounting_timeline(events, POLICY, item_id="account-work")
    assert release["phases"]["integration"]["seconds"] == 180
    assert release["phases"]["verification"]["seconds"] == 60

    other = accounting_timeline(events, POLICY, item_id="account-work", attempt_id="a2")
    assert not other["phases"]["integration"]["intervals"]
    assert not other["phases"]["verification"]["intervals"]
    assert other["phases"]["verification"]["seconds"] is None


def test_verification_requires_the_matching_train_and_ok_true():
    base = lifecycle() + [ev("item.landed", dict(
        attempt_id="a1", train_id="tr-1", fix_commits=[]), 8)]
    cases = [
        dict(work="lanectl#2898", train_id="tr-other", closed=True, ok=True),
        dict(work="lanectl#2898", train_id="tr-1", closed=True, ok=False),
        dict(work="lanectl#2898", train_id="tr-1", closed=False, ok=True,
             owner_reported=True, pending_owner=True),
    ]
    for data in cases:
        result = accounting_timeline(base + [ev("work.synced", data, 11)], POLICY,
                                     item_id="account-work")
        assert result["phases"]["verification"]["seconds"] is None
        assert result["phases"]["verification"]["intervals"][0]["end"] is None


def test_render_labels_estimates_units_coverage_and_unknowns():
    result = accounting_timeline([usage("adapter", {"output_tokens": "unknown"})],
                                 POLICY, item_id="account-work")
    text = render_timeline(result)
    lowered = text.lower()
    assert "estimate" in lowered and "19" in text
    assert "output_tokens" in text
    assert "unknown" in lowered
    # Absent measurements are not inferred as full attribution coverage.
    assert "coverage=unknown" in render_timeline(
        accounting_timeline([], POLICY, item_id="account-work")).lower()


def test_cli_plugin_uses_validated_log_and_policy_prices(tmp_path, monkeypatch, capsys):
    log = EventLog(tmp_path / "events.jsonl")
    log.append("usage.recorded", dict(provider="test", source="adapter",
                                     units={"output_tokens": 100}, model="model-a"),
               item_id="account-work")
    monkeypatch.setattr("lanectl.accounting._load_policy_raw", lambda: POLICY)

    class Args:
        item = "account-work"
        attempt = None
        json = True

    assert _cmd(Args(), log) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["price_revision"] == 19
    assert result["usage"]["lane"]["usd_est"] == pytest.approx(100 * 2.0 / 1_000_000)
