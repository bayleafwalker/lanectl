"""Acceptance: dollar estimates from published prices (planner-owned)."""
import pytest

from lanectl import report
from lanectl.contracts import make_event
from lanectl.costs import cost_summary, price_usage

M = "opencode-go/deepseek-v4.1-flash"
PRICES = {
    "peak_hours_utc": [[1, 4], [6, 10]],
    "peak_weekdays": [0, 1, 2, 3, 4],
    "models": {M: {"offpeak": {"input": 0.15, "output": 0.60, "cache_read": 0.003},
                   "peak": {"input": 0.30, "output": 1.20, "cache_read": 0.006}}},
}
POLICY = {"revision": 1, "providers": {"opencode": {"unit": "output_tokens", "prices": PRICES}}}
MILLION = {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_tokens": 1_000_000}
SATURDAY = "2026-11-07T12:00:00Z"
MONDAY_PEAK = "2026-11-09T07:30:00Z"
MONDAY_OFFPEAK = "2026-11-09T05:00:00Z"


def test_offpeak_and_peak_prices():
    assert price_usage(MILLION, M, SATURDAY, PRICES) == pytest.approx(0.753)
    assert price_usage(MILLION, M, MONDAY_PEAK, PRICES) == pytest.approx(1.506)
    assert price_usage(MILLION, M, MONDAY_OFFPEAK, PRICES) == pytest.approx(0.753)


def test_reasoning_is_priced_as_output_and_other_units_ignored():
    units = {"reasoning_tokens": 1_000_000, "steps": 50, "cost_usd": 0.0, "cache_write_tokens": 0}
    assert price_usage(units, M, SATURDAY, PRICES) == pytest.approx(0.60)


def test_unpriced_model_is_none_not_zero():
    assert price_usage(MILLION, "anthropic/claude", SATURDAY, PRICES) is None


def _usage(units, ts, model=M, provider="opencode"):
    return make_event("usage.recorded", {"provider": provider, "source": "adapter", "model": model,
                                         "units": units}, ts=ts)


def test_summary_per_model_with_unpriced_count():
    ev = [_usage(MILLION, SATURDAY), _usage(MILLION, MONDAY_PEAK),
          _usage({"output_tokens": 10}, SATURDAY, model="claude-sonnet-5-5", provider="anthropic")]
    s = cost_summary(ev, POLICY)
    assert s[M]["usd_est"] == pytest.approx(2.259) and s[M]["events"] == 2
    assert s["_unpriced"] == {"events": 1}


def test_report_section(tmp_path, monkeypatch):
    gov = tmp_path / "governance"
    gov.mkdir()
    (gov / "allocation.toml").write_text(
        'revision = 1\n[providers.opencode]\nunit = "output_tokens"\n'
        '[providers.opencode.prices]\npeak_hours_utc = [[1, 4], [6, 10]]\npeak_weekdays = [0, 1, 2, 3, 4]\n'
        f'[providers.opencode.prices.models."{M}"]\n'
        'offpeak = { input = 0.15, output = 0.60, cache_read = 0.003 }\n'
        'peak = { input = 0.30, output = 1.20, cache_read = 0.006 }\n')
    monkeypatch.setenv("LANECTL_HOME", str(tmp_path))
    text = report.format_report(report.build_report([_usage(MILLION, SATURDAY)]))
    assert "cost_usd" in text
    line = next(line for line in text.splitlines() if line.strip().startswith(M + ":") and "usd=" in line)
    assert "usd=0.75" in line and "events=1" in line
