"""Unit coverage for operator cost per landed release."""
import pytest

from lanectl import report
from lanectl.contracts import make_event
from lanectl.operator_cost import operator_cost

M = "opencode-go/deepseek-v4.1-flash"
PRICES = {
    "peak_hours_utc": [],
    "peak_weekdays": [],
    "models": {M: {"offpeak": {"input": 1.0, "output": 2.0}}},
}
POLICY = {"revision": 1, "providers": {"opencode": {"unit": "output_tokens", "prices": PRICES}}}
TS = "2026-11-07T12:00:00Z"
OP = "claude-code-interactive"


def _usage(item, source, units, model=M):
    return make_event("usage.recorded", {"provider": "x", "source": source,
                                         "model": model, "units": units},
                      item_id=item, ts=TS)


def _landed(item):
    return make_event("item.landed", {"attempt_id": f"{item}-a1", "train_id": "t",
                                      "fix_commits": []}, item_id=item, ts=TS)


def test_per_landed_averages_only_over_landed_releases():
    events = [
        _usage("aa", "adapter", {"output_tokens": 1_000_000}),
        _usage("bb", "adapter", {"output_tokens": 1_000_000}),
        _landed("aa"),
    ]
    s = operator_cost(events, POLICY)
    assert s["landed"] == 1
    assert s["lane_usd_per_landed"] == pytest.approx(2.0)
    assert s["operator_usd_per_landed"] == pytest.approx(0.0)


def test_lane_usage_without_item_is_dropped_not_unpriced():
    s = operator_cost([_usage(None, "adapter", {"output_tokens": 1_000_000})], POLICY)
    assert s["releases"] == {}
    assert s["unpriced_events"] == 0
    assert s["unattributed_operator_usd"] == 0.0


def test_operator_usage_without_item_is_unattributed():
    s = operator_cost([_usage(None, OP, {"output_tokens": 1_000_000})], POLICY)
    assert s["releases"] == {}
    assert s["unattributed_operator_usd"] == pytest.approx(2.0)


def test_report_fn_loads_governance(tmp_path, monkeypatch):
    gov = tmp_path / "governance"
    gov.mkdir()
    (gov / "allocation.toml").write_text(
        'revision = 1\n[providers.opencode]\nunit = "output_tokens"\n'
        '[providers.opencode.prices]\npeak_hours_utc = []\npeak_weekdays = []\n'
        f'[providers.opencode.prices.models."{M}"]\noffpeak = {{ input = 1.0, output = 2.0 }}\n')
    monkeypatch.setenv("LANECTL_HOME", str(tmp_path))
    text = report.format_report(report.build_report(
        [_usage("aa", "adapter", {"output_tokens": 1_000_000})]))
    assert "operator_cost (estimate from published prices):" in text
    assert "landed=0 lane_usd/landed=- operator_usd/landed=-" in text
