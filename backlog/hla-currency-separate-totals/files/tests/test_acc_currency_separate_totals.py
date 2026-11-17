"""Independent monetary denomination acceptance; only synthetic facts."""
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from apps.api.app import create_app
from packages.domains.finance.pipelines.account_transaction_service import AccountTransactionService
from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
from packages.pipelines.transformation_service import TransformationService
from packages.storage.duckdb_store import DuckDBStore
from packages.storage.run_metadata import RunMetadataRepository

KEYS = ["mart_monthly_cashflow", "mart_monthly_cashflow_by_counterparty", "mart_spend_by_category_monthly",
        "mart_utility_cost_summary", "mart_utility_cost_trend_monthly", "mart_household_overview"]
MONTH = date.today().strftime("%Y-%m")


@contextmanager
def api(root, *, published=False):
    root.mkdir(parents=True, exist_ok=True)
    ts = TransformationService(DuckDBStore.memory())
    service = AccountTransactionService(landing_root=root / "landing", metadata_repository=RunMetadataRepository(root / "runs.db"))
    reporting = ReportingService(ts, access_mode=ReportingAccessMode.PUBLISHED) if published else None
    with TestClient(create_app(service, transformation_service=ts, reporting_service=reporting)) as client:
        yield ts, client


def transactions(currency_amounts):
    return [{"booked_at": f"{MONTH}-{day:02}", "account_id": "synthetic",
             "counterparty_name": "same-counterparty", "amount": str(amount),
             "currency": currency, "description": f"synthetic-{day}-{currency}"}
            for day, currency, amount in currency_amounts]


def bill(day, currency, amount, meter="meter"):
    at = f"{MONTH}-{day:02}"
    return {"meter_id": meter, "meter_name": meter, "provider": "synthetic",
            "utility_type": "electricity", "location": "home", "billing_period_start": at,
            "billing_period_end": at, "billed_amount": str(amount), "currency": currency,
            "billed_quantity": "100", "usage_unit": "kWh", "invoice_date": at}


def usage(day, meter="meter"):
    at = f"{MONTH}-{day:02}"
    return {"meter_id": meter, "meter_name": meter, "utility_type": "electricity",
            "location": "home", "usage_start": at, "usage_end": at,
            "usage_quantity": "100", "usage_unit": "kWh", "reading_source": "synthetic"}


def load(ts, finance, bills=(), usages=()):
    if finance:
        ts.load_transactions(transactions(finance), run_id="finance-synthetic")
    if bills:
        ts.load_bills(list(bills), run_id="bill-synthetic")
    if usages:
        ts.load_utility_usage(list(usages), run_id="usage-synthetic")
    ts.refresh_publications(KEYS)


def rows(client, path):
    result = client.get(path)
    assert result.status_code == 200, result.text
    return result.json()["rows"]


def by_currency(data, field, expected):
    assert len(data) == len(expected), data
    assert {r.get("currency") for r in data} == set(expected), data
    actual = {r["currency"]: Decimal(str(r[field])) for r in data}
    assert actual == {k: Decimal(str(v)) for k, v in expected.items()}, data


def test_finance_separates_same_month_and_counterparty(tmp_path):
    with api(tmp_path) as (ts, client):
        load(ts, [(3, "USD", 100), (1, "EUR", 200), (4, "USD", -20), (2, "EUR", -30)])
        by_currency(rows(client, "/reports/monthly-cashflow"), "net", {"EUR": 170, "USD": 80})


def test_utility_monthly_and_trend_do_not_blend_currency_or_unit_price(tmp_path):
    with api(tmp_path) as (ts, client):
        load(ts, [], [bill(3, "USD", 100), bill(1, "EUR", 200)], [usage(3), usage(1)])
        summary = rows(client, "/reports/utility-cost-summary")
        by_currency(summary, "billed_amount", {"EUR": 200, "USD": 100})


def test_household_and_scalar_consumers_handle_mixed_denominations(tmp_path):
    with api(tmp_path) as (ts, client):
        load(ts, [(3, "USD", 100), (1, "EUR", 200), (4, "USD", -20), (2, "EUR", -30)],
             [bill(3, "USD", 100), bill(1, "EUR", 200)], [usage(3), usage(1)])
        by_currency(rows(client, "/reports/household-overview"), "cashflow_net", {"EUR": 170, "USD": 80})


def test_single_usd_does_not_borrow_eur_from_utilities(tmp_path):
    with api(tmp_path) as (ts, client):
        load(ts, [(1, "USD", 250)], [bill(1, "EUR", 300)], [usage(1)])
        cash = client.get("/api/ha/metrics/current-month/net-cashflow")
        assert cash.status_code == 200 and cash.json() == {"value": 250.0, "unit": "USD"}


def test_single_eur_control(tmp_path):
    with api(tmp_path) as (ts, client):
        load(ts, [(1, "EUR", 250)], [bill(1, "EUR", 300)], [usage(1)])
        monthly = rows(client, "/reports/monthly-cashflow")
        assert len(monthly) == 1 and Decimal(str(monthly[0]["net"])) == 250
        trend = rows(client, "/reports/utility-cost-trend")
        by_currency(trend, "total_cost", {"EUR": 300})
        assert client.get("/api/ha/metrics/current-month/net-cashflow").json() == {"value": 250.0, "unit": "EUR"}
        assert client.get("/api/ha/metrics/current-month/electricity-cost").json() == {"value": 300.0, "unit": "EUR"}


def test_usage_only_is_not_an_observed_zero_bill(tmp_path):
    with api(tmp_path) as (ts, client):
        load(ts, [], [bill(1, "USD", 0, "zero-bill")], [usage(1, "zero-bill"), usage(1, "usage-only")])
        summary = {r["meter_id"]: r for r in rows(client, "/reports/utility-cost-summary")}
        assert set(summary) == {"zero-bill", "usage-only"}
        assert summary["zero-bill"]["currency"] == "USD" and summary["zero-bill"]["bill_count"] == 1
        assert Decimal(str(summary["zero-bill"]["billed_amount"])) == 0
        assert summary["usage-only"]["currency"] is None and summary["usage-only"]["bill_count"] == 0
        assert summary["usage-only"]["coverage_status"] == "usage_only"


def test_empty_and_unavailable_are_distinct(tmp_path):
    with api(tmp_path / "empty") as (ts, client):
        ts.refresh_publications(KEYS)
        assert rows(client, "/reports/monthly-cashflow") == []
    with api(tmp_path / "unavailable", published=True) as (_, client):
        result = client.get("/reports/monthly-cashflow")
        assert result.status_code == 404 and "Published reporting relation is unavailable" in result.json()["error"]


def test_counterparty_currency_groups(tmp_path):
    with api(tmp_path) as (ts, client):
        load(ts, [(3, "USD", 100), (1, "EUR", 200), (4, "USD", -20), (2, "EUR", -30)])
        by_currency(rows(client, "/reports/monthly-cashflow-by-counterparty"), "net", {"EUR": 170, "USD": 80})


def test_utility_trend_separates_price_per_currency(tmp_path):
    with api(tmp_path) as (ts, client):
        load(ts, [], [bill(3, "USD", 100), bill(1, "EUR", 200)], [usage(3), usage(1)])
        trend = rows(client, "/reports/utility-cost-trend")
        by_currency(trend, "total_cost", {"EUR": 200, "USD": 100})
        by_currency(trend, "unit_price_effective", {"EUR": 2, "USD": 1})


def test_mixed_currency_scalars_are_unavailable(tmp_path):
    with api(tmp_path) as (ts, client):
        load(ts, [(3, "USD", 80), (1, "EUR", 170)],
             [bill(3, "USD", 100), bill(1, "EUR", 200)], [usage(3), usage(1)])
        for path in ("/api/ha/metrics/current-month/net-cashflow", "/api/ha/metrics/current-month/electricity-cost"):
            result = client.get(path)
            assert result.status_code == 200
            assert result.json() == {"value": None, "unit": ""}, (path, result.json())


def test_usage_only_scalar_is_unavailable(tmp_path):
    with api(tmp_path) as (ts, client):
        load(ts, [], [], [usage(1)])
        result = client.get("/api/ha/metrics/current-month/electricity-cost")
        assert result.status_code == 200 and result.json() == {"value": None, "unit": ""}


def test_non_whitelisted_currency_is_preserved(tmp_path):
    with api(tmp_path) as (ts, client):
        load(ts, [(1, "ZZZ", 17)])
        by_currency(rows(client, "/reports/monthly-cashflow"), "net", {"ZZZ": 17})


def test_currency_oracle_rejects_blended_missing_and_relabelled_rows():
    import pytest

    good = [{"currency": "EUR", "net": "170"}, {"currency": "USD", "net": "80"}]
    by_currency(good, "net", {"EUR": 170, "USD": 80})
    wrong = [
        [{"currency": "EUR", "net": "250"}],
        [{"currency": "EUR", "net": "170"}],
        [{"currency": "EUR", "net": "80"}, {"currency": "USD", "net": "170"}],
        [{"currency": "EUR", "net": "170"}, {"currency": "EUR", "net": "80"}],
    ]
    for mutation in wrong:
        with pytest.raises(AssertionError):
            by_currency(mutation, "net", {"EUR": 170, "USD": 80})


def test_observed_zero_bill_is_an_available_scalar(tmp_path):
    with api(tmp_path) as (ts, client):
        load(ts, [], [bill(1, "USD", 0)], [usage(1)])
        result = client.get("/api/ha/metrics/current-month/electricity-cost")
        assert result.status_code == 200 and result.json() == {"value": 0.0, "unit": "USD"}


def test_spending_by_category_preserves_currency(tmp_path):
    with api(tmp_path) as (ts, client):
        load(ts, [(4, "USD", -20), (2, "EUR", -30)])
        by_currency(rows(client, "/reports/spend-by-category-monthly"), "total_expense", {"EUR": 30, "USD": 20})


def assert_disjoint_household_contributions(data):
    def has(currency, field, amount):
        return any(r.get("currency") == currency and r.get(field) is not None
                   and Decimal(str(r[field])) == Decimal(str(amount)) for r in data)
    assert has("USD", "cashflow_net", 250), data
    assert has("EUR", "utility_cost_total", 300), data
    for row in data:
        for field, allowed in (("cashflow_net", "USD"), ("utility_cost_total", "EUR")):
            value = row.get(field)
            if value is not None and Decimal(str(value)) != 0:
                assert row.get("currency") == allowed, (field, row)


def test_household_preserves_disjoint_domain_contributions(tmp_path):
    with api(tmp_path) as (ts, client):
        load(ts, [(1, "USD", 250)], [bill(1, "EUR", 300)], [usage(1)])
        assert_disjoint_household_contributions(rows(client, "/reports/household-overview"))


def test_disjoint_oracle_rejects_dropped_or_relabelled_contributions():
    import pytest
    good = [{"currency": "USD", "cashflow_net": 250}, {"currency": "EUR", "utility_cost_total": 300}]
    assert_disjoint_household_contributions(good)
    assert_disjoint_household_contributions([
        {"currency": "USD", "cashflow_net": 250, "utility_cost_total": 0},
        {"currency": "EUR", "cashflow_net": None, "utility_cost_total": 300},
        {"currency": "ZZZ", "cashflow_net": 0, "utility_cost_total": None},
    ])
    wrong = [[{"currency": "USD", "cashflow_net": 250, "utility_cost_total": 300},
              {"currency": "EUR", "cashflow_net": 250, "utility_cost_total": 300}],
             good[:1], good[1:],
             good + [{"currency": "EUR", "cashflow_net": 1}],
             good + [{"currency": "ZZZ", "utility_cost_total": 1}],
             [{"currency": "EUR", "cashflow_net": 250}, good[1]],
             [good[0], {"currency": "USD", "utility_cost_total": 300}]]
    for mutation in wrong:
        with pytest.raises(AssertionError):
            assert_disjoint_household_contributions(mutation)
