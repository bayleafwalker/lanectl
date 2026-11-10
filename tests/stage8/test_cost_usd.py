"""Unit coverage for dollar estimates from published prices."""
import pytest

from lanectl import report
from lanectl.contracts import make_event
from lanectl.costs import cost_summary, price_usage

M = "opencode-go/deepseek-v4.1-flash"
MILLION = {"input_tokens": 1_000_000, "output_tokens": 1_000_000,
           "cache_read_tokens": 1_000_000}
PRICES = {
    "peak_hours_utc": [[1, 4], [6, 10]],
    "peak_weekdays": [0, 1, 2, 3, 4],
    "models": {M: {"offpeak": {"input": 0.15, "output": 0.60, "cache_read": 0.003},
                   "peak": {"input": 0.30, "output": 1.20, "cache_read": 0.006}}},
}
OFFPEAK = 0.753
PEAK = 1.506


def test_peak_hour_boundary_is_half_open():
    assert price_usage(MILLION, M, "2026-11-09T03:59:00Z", PRICES) == pytest.approx(PEAK)
    assert price_usage(MILLION, M, "2026-11-09T04:00:00Z", PRICES) == pytest.approx(OFFPEAK)
    assert price_usage(MILLION, M, "2026-11-09T00:59:00Z", PRICES) == pytest.approx(OFFPEAK)
    assert price_usage(MILLION, M, "2026-11-09T06:00:00Z", PRICES) == pytest.approx(PEAK)


def test_naive_timestamp_is_read_as_utc():
    assert price_usage(MILLION, M, "2026-11-09T07:30:00", PRICES) == pytest.approx(PEAK)
    assert price_usage(MILLION, M, "2026-11-09T05:00:00", PRICES) == pytest.approx(OFFPEAK)


def test_peak_range_wraps_past_midnight_without_moving_weekday():
    prices = {"peak_hours_utc": [[22, 2]], "peak_weekdays": [0],
              "models": {M: {"offpeak": {"output": 1.0}, "peak": {"output": 2.0}}}}
    units = {"output_tokens": 1_000_000}
    assert price_usage(units, M, "2026-11-09T23:30:00Z", prices) == pytest.approx(2.0)
    assert price_usage(units, M, "2026-11-10T01:00:00Z", prices) == pytest.approx(1.0)
    assert price_usage(units, M, "2026-11-08T23:30:00Z", prices) == pytest.approx(1.0)


def test_model_without_peak_table_is_always_offpeak():
    prices = {"peak_hours_utc": [[0, 24]], "peak_weekdays": [0, 1, 2, 3, 4, 5, 6],
              "models": {M: {"offpeak": {"output": 0.60}}}}
    assert price_usage({"output_tokens": 1_000_000}, M, "2026-11-09T07:30:00Z",
                       prices) == pytest.approx(0.60)


def _usage(units, ts="2026-11-07T12:00:00Z", model=M, provider="opencode"):
    return make_event("usage.recorded", {"provider": provider, "source": "adapter",
                                        "model": model, "units": units}, ts=ts)


def test_summary_falls_through_providers_that_do_not_list_the_model():
    policy = {"providers": {"other": {"prices": {"models": {}}},
                            "opencode": {"prices": PRICES}}}
    summary = cost_summary([_usage(MILLION)], policy)
    assert summary[M] == {"usd_est": pytest.approx(OFFPEAK), "events": 1}
    assert summary["_unpriced"] == {"events": 0}


def test_summary_ignores_events_without_a_model_and_accumulates():
    ev = [_usage(MILLION), _usage({"output_tokens": 1_000_000}, ts="2026-11-09T07:30:00Z"),
          make_event("usage.recorded", {"provider": "opencode", "source": "adapter",
                                        "units": {"output_tokens": 5}})]
    summary = cost_summary(ev, {"providers": {"opencode": {"prices": PRICES}}})
    assert summary[M]["events"] == 2
    assert summary[M]["usd_est"] == pytest.approx(OFFPEAK + 1.20)
    assert summary["_unpriced"] == {"events": 0}


def test_summary_without_any_price_table_counts_everything_unpriced():
    summary = cost_summary([_usage(MILLION)], {})
    assert summary == {"_unpriced": {"events": 1}}


def test_report_says_no_price_table_when_governance_has_none(tmp_path, monkeypatch):
    monkeypatch.setenv("LANECTL_HOME", str(tmp_path))
    text = report.format_report(report.build_report([_usage(MILLION)]))
    assert "cost_usd (estimate from published prices):" in text
    assert "no price table" in text


def test_report_lists_models_sorted_before_unpriced(tmp_path, monkeypatch):
    first, last = "aa/first", "zz/last"
    gov = tmp_path / "governance"
    gov.mkdir()
    (gov / "allocation.toml").write_text(
        'revision = 1\n[providers.opencode.prices]\npeak_weekdays = [0, 1, 2, 3, 4]\n'
        'peak_hours_utc = [[1, 4]]\n'
        f'[providers.opencode.prices.models."{last}"]\noffpeak = {{ output = 1.0 }}\n'
        f'[providers.opencode.prices.models."{first}"]\noffpeak = {{ output = 2.0 }}\n')
    monkeypatch.setenv("LANECTL_HOME", str(tmp_path))
    text = report.format_report(report.build_report(
        [_usage({"output_tokens": 1_000_000}, model=last),
         _usage({"output_tokens": 500_000}, model=first),
         _usage({"output_tokens": 500_000}, model="un/priced")]))
    lines = text.splitlines()
    assert lines.index(f"  {first}: usd=1.00 events=1") < lines.index(f"  {last}: usd=1.00 events=1")
    assert "  unpriced usage events=1" in lines
