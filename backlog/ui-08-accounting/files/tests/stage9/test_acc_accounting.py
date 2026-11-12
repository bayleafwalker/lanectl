import pytest

from lanectl.accounting import accounting_timeline, render_timeline
from lanectl.contracts import make_event


POLICY = {"revision": 19, "providers": {"test": {"prices": {
    "models": {"model-a": {"offpeak": {"input": 1.0, "output": 2.0}}}}}}}


def ev(kind, data, minute, item="account-work"):
    return make_event(kind, data, item_id=item, ts=f"2026-11-12T10:{minute:02d}:00Z")


def history():
    return [ev("release.published", dict(release_id="account-work", revision=1), 0),
            ev("item.claimed", dict(attempt_id="account-work-a1", lane="implement", model="model-a", worker="fake"), 2),
            ev("attempt.finished", dict(attempt_id="account-work-a1", outcome="done", exit_code=0, head_sha="abc"), 5),
            ev("item.landed", dict(attempt_id="account-work-a1", train_id="tr-19", fix_commits=[]), 8),
            ev("work.synced", dict(work="lanectl#2898", train_id="tr-19", closed=False, ok=True,
                                  owner_reported=True, pending_owner=True), 9)]


def usage(source, units, *, model="model-a", item="account-work", attempt="account-work-a1", provider="test"):
    return ev("usage.recorded", dict(provider=provider, source=source, units=units,
             model=model, attempt_id=attempt), 5, item=item)


def test_phase_durations_separate_waiting_and_execution_and_pending_verification():
    result = accounting_timeline(history(), POLICY, item_id="account-work")
    phases = result["phases"]
    assert phases["queued"]["seconds"] == 120
    assert phases["execution"]["seconds"] == 180
    assert phases["integration"]["seconds"] == 180
    assert phases["verification"]["seconds"] is None
    for phase in ("queued", "execution", "integration"):
        assert phases[phase]["intervals"]
        assert phases[phase]["intervals"][0]["source"] == "lanectl.events"
    closed = history() + [ev("work.synced", dict(work="lanectl#2898", train_id="tr-19", closed=True, ok=True), 11)]
    assert accounting_timeline(closed, POLICY, item_id="account-work")["phases"]["verification"]["seconds"] == 180


def test_cost_preserves_units_revision_estimates_and_attribution():
    events = history() + [usage("adapter", {"output_tokens": 1_000_000}),
        usage("claude-code-interactive", {"input_tokens": 500_000}, attempt=None),
        usage("claude-code-interactive", {"input_tokens": 10}, item=None, attempt=None)]
    result = accounting_timeline(events, POLICY, item_id="account-work")
    assert result["price_revision"] == 19
    assert result["usage"]["lane"]["usd_est"] == pytest.approx(2.0)
    assert result["usage"]["operator"]["usd_est"] == pytest.approx(0.5)
    assert result["usage"]["lane"]["units"]["output_tokens"] == 1_000_000
    assert result["usage"]["lane"]["estimate"] is True
    assert result["attribution"]["attributed_events"] == 2
    assert result["attribution"]["unattributed_events"] == 1
    text = render_timeline(result)
    assert "estimate" in text and "19" in text and "unknown" in text.lower()


def test_missing_or_partial_prices_never_mean_zero_and_provider_does_not_cross_price():
    events = [usage("adapter", {"output_tokens": 100}),
              usage("adapter", {"output_tokens": 50}, model="no-price")]
    result = accounting_timeline(events, POLICY, item_id="account-work")
    lane = result["usage"]["lane"]
    assert lane["usd_est"] is None and lane["known_usd_est"] > 0
    assert lane["unpriced_events"] == 1
    assert result["usage"]["operator"]["usd_est"] is None
    for event in (usage("adapter", {"mystery_units": 3}),
                  usage("adapter", {"output_tokens": 3}, provider="other")):
        assert accounting_timeline([event], POLICY, item_id="account-work")["usage"]["lane"]["usd_est"] is None


def test_attempt_filter_and_retries_do_not_charge_other_attempts_or_waits():
    events = history()[:3] + [
        ev("item.claimed", dict(attempt_id="account-work-a2", lane="implement", model="model-a", worker="fake"), 10),
        ev("attempt.finished", dict(attempt_id="account-work-a2", outcome="done", exit_code=0, head_sha="def"), 12),
        usage("adapter", {"output_tokens": 10}),
        usage("adapter", {"output_tokens": 20}, attempt="account-work-a2"),
        usage("claude-code-interactive", {"input_tokens": 30}, attempt=None)]
    result = accounting_timeline(events, POLICY, item_id="account-work")
    assert result["phases"]["execution"]["seconds"] == 300
    second = accounting_timeline(events, POLICY, item_id="account-work", attempt_id="account-work-a2")
    assert second["usage"]["lane"]["units"]["output_tokens"] == 20
    assert second["usage"]["operator"]["usd_est"] is None
    assert second["phases"]["execution"]["seconds"] == 120
