"""Synthetic source-to-publication fixtures for the three domain cards."""
import os
import tempfile
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import uvicorn
from psycopg import sql

from apps.api.app import create_app
from packages.domains.finance.pipelines.account_transaction_service import AccountTransactionService
from packages.pipelines.household_packages import (
    BUILTIN_TRANSFORMATION_PACKAGE_SPECS_BY_HANDLER_KEY,
)
from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
from packages.pipelines.transformation_service import TransformationService
from packages.storage.duckdb_store import DuckDBStore
from packages.storage.postgres_reporting import PostgresReportingStore
from packages.storage.run_metadata import RunMetadataRepository

PUBLICATIONS = (
    "mart_monthly_cashflow", "mart_utility_cost_summary", "mart_utility_cost_trend_monthly",
    "mart_service_health_current", "mart_subscription_summary", "mart_upcoming_fixed_costs_30d",
    "mart_contract_price_current", "mart_contract_review_candidates", "mart_contract_renewal_watchlist",
    "mart_transaction_anomalies_current", "mart_open_attention_items",
)
HISTORY = "mart_service_health_history"
RAW_RELATIONS = (
    "fact_transaction", "fact_transaction_current", "fact_bill", "fact_utility_usage",
    "fact_service_health", "dim_service",
)
FIRST = "2026-01-05T06:03:17+00:00"
SECOND = "2026-03-23T19:11:42+00:00"


def observed_month(today, offset):
    absolute = today.year * 12 + today.month - 1 + offset
    return date(absolute // 12, absolute % 12 + 1, 1)


def finance_points(today):
    return [(observed_month(today, offset), unit, value)
            for offset, unit, value in ((-5, "USD", 200), (-4, "EUR", 100), (-2, "EUR", 160),
                                         (-1, "USD", 260), (0, "EUR", 300))]


def utility_points(today):
    return [(observed_month(today, offset), unit, value)
            for offset, unit, value in ((-5, "USD", 80), (-4, "EUR", 100),
                                         (-2, "USD", 0), (-1, "EUR", 150))]


def observation(service_id, timestamp, state, criticality="standard", *, name=None):
    return {"service_id": service_id, "service_name": name or service_id, "recorded_at": timestamp,
            "state": state, "criticality": criticality}


def load_service_cohorts(ts, scenario):
    if scenario == "normal":
        first = [
            observation("z-critical", FIRST, "degraded", "critical", name="Alpha proxy"),
            observation("a-critical", FIRST, "running", "critical", name="Zeta relay"),
            observation("standard-node", FIRST, "running"),
            observation("background-node", FIRST, "running", "background"),
            observation("a-critical", "2026-01-05T06:02:01+00:00", "stopped", "critical", name="Zeta relay"),
        ]
        second = [
            observation("a-critical", SECOND, "stopped", "critical", name="Zeta relay"),
            observation("background-node", SECOND, "degraded", "background"),
            observation("z-critical", SECOND, "degraded", "critical", name="Alpha proxy"),
            observation("standard-node", SECOND, "stopped"),
        ]
    elif scenario == "recovery":
        first = [observation("alpha", FIRST, "degraded"), observation("beta", FIRST, "running")]
        second = [observation("beta", SECOND, "running"), observation("alpha", SECOND, "running")]
    elif scenario == "changed":
        first = [observation("alpha", FIRST, "degraded"), observation("beta", FIRST, "running")]
        second = [observation("alpha", SECOND, "running"), observation("gamma", SECOND, "running")]
    elif scenario in {"unknown-shared", "unknown-changed"}:
        first = [observation("alpha", FIRST, "degraded"), observation("beta", FIRST, "unknown")]
        later_member = "beta" if scenario == "unknown-shared" else "gamma"
        second = [observation("alpha", SECOND, "running"),
                  observation(later_member, SECOND, "unknown")]
    elif scenario in {"one", "unknown"}:
        first = [observation("alpha", FIRST, "degraded" if scenario == "one" else "unknown")]
        second = []
    elif scenario == "ranks":
        first = [
            observation("a-unknown", FIRST, "stopped", "custom"),
            observation("b-background", FIRST, "degraded", "background", name="Background relay"),
            observation("z-standard", FIRST, "stopped", "standard", name="Standard relay"),
        ]
        second = []
    else:
        return
    # Load newer first to separate observation order from ingestion order.
    assert ts.load_service_health(second, run_id="irregular-second", source_system="synthetic") == len(second)
    assert ts.load_service_health(first, run_id="irregular-first", source_system="synthetic") == len(first)


def utility_source(meter):
    return {"meter_id": meter, "meter_name": meter, "utility_type": "electricity", "location": "home",
            "usage_unit": "kWh"}


def load_sources(ts, today, scenario):
    load_service_cohorts(ts, scenario)
    if scenario in {"normal", "usage-only"}:
        newest = observed_month(today, 0)
        assert ts.load_utility_usage([{
            **utility_source("unbilled"), "usage_start": str(newest), "usage_end": str(newest),
            "usage_quantity": "50", "reading_source": "synthetic",
        }], run_id="observed-usage") == 1
    if scenario == "one":
        assert ts.load_transactions([{
            "booked_at": str(today), "account_id": "home", "counterparty_name": "single",
            "amount": "42", "currency": "EUR", "description": "single month",
        }], run_id="one-finance-month") == 1
        assert ts.load_bills([{
            **utility_source("meter-one-bill"), "provider": "synthetic supplier",
            "billing_period_start": str(today), "billing_period_end": str(today), "invoice_date": str(today),
            "currency": "USD", "billed_amount": "0", "billed_quantity": "100",
        }], run_id="one-utility-month") == 1
    if scenario not in {"normal", "invalid-priorities"}:
        return
    transactions = [{
        "booked_at": str(day), "account_id": "home", "counterparty_name": "Known salary",
        "amount": str(amount), "currency": unit, "description": f"month {day}",
    } for day, unit, amount in finance_points(today)]
    transactions.append({"booked_at": str(today), "account_id": "home", "counterparty_name": "Anchor Books",
                         "amount": "-120", "currency": "EUR", "description": "one observed anomaly"})
    assert ts.load_transactions(list(reversed(transactions)), run_id="source-finance") == len(transactions)
    bills = [{
        **utility_source(f"meter-{unit}"), "provider": "synthetic supplier",
        "billing_period_start": str(day), "billing_period_end": str(day), "invoice_date": str(day),
        "currency": unit, "billed_amount": str(amount), "billed_quantity": "100",
    } for day, unit, amount in utility_points(today)]
    assert ts.load_bills(list(reversed(bills)), run_id="source-utility") == len(bills)
    assert ts.load_subscriptions([{
        "contract_id": "low-subscription", "service_name": "Low subscription", "provider": "Budget",
        "billing_cycle": "weekly", "amount": "10", "currency": "EUR",
        "start_date": str(today - timedelta(days=7)), "end_date": None,
    }], run_id="lower-finance-attention") == 1
    assert ts.load_contract_prices([{
        "contract_id": key, "contract_name": provider, "provider": provider, "contract_type": "electricity",
        "price_component": "energy", "billing_cycle": "per_kwh", "unit_price": "0.30", "currency": "EUR",
        "quantity_unit": "kWh", "valid_from": str(today - timedelta(days=30)),
        "valid_to": str(today + timedelta(days=days)),
    } for key, provider, days in (("near-renewal", "Harbor Utility", 10),
                                  ("later-renewal", "Upland Utility", 25))],
        run_id="source-contracts") == 2


@contextmanager
def domain_world(root, scenario, *, access="warehouse", invalid_utility_rank=0):
    root.mkdir(parents=True, exist_ok=True)
    store = DuckDBStore.memory()
    schema = "domain_cards_" + uuid4().hex
    dsn = os.environ["DOMAIN_CARDS_POSTGRES_DSN"] if access != "warehouse" else None
    try:
        ts = TransformationService(store)
        today = store.fetchall("SELECT CURRENT_DATE")[0][0]
        load_sources(ts, today, scenario)
        homelab = BUILTIN_TRANSFORMATION_PACKAGE_SPECS_BY_HANDLER_KEY["homelab"]
        keys = list(PUBLICATIONS)
        if HISTORY in homelab.refresh_publication_keys:
            assert HISTORY in homelab.publication_keys, "history must be in normal Homelab publication"
            keys.append(HISTORY)
        assert set(keys) <= set(ts.refresh_publications(keys))

        if scenario == "invalid-priorities":
            # Keep the source-derived actions. Simulate invalid persisted ranks
            # on lower-priority actions and retain a valid winner in each domain.
            store.execute("UPDATE mart_open_attention_items SET severity = 99 "
                          "WHERE source_domain = 'finance' AND severity = 1")
            store.execute("UPDATE mart_open_attention_items SET severity = ? "
                          "WHERE title = 'Upcoming renewal: Upland Utility'", [invalid_utility_rank])
            assert store.fetchall("SELECT count(*) FROM mart_open_attention_items WHERE severity = 99")[0][0] > 0
            assert store.fetchall("SELECT severity FROM mart_open_attention_items "
                                  "WHERE title = 'Upcoming renewal: Upland Utility'") == [(invalid_utility_rank,)]

        if access == "warehouse":
            reporting = ReportingService(ts, access_mode=ReportingAccessMode.WAREHOUSE)
        else:
            with psycopg.connect(dsn, autocommit=True) as conn:
                conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            reporting = ReportingService(ts, publication_store=PostgresReportingStore(dsn, schema=schema),
                                         access_mode=ReportingAccessMode.PUBLISHED)
            if access in {"published", "partial"}:
                published = [key for key in keys if access != "partial" or key != "mart_service_health_current"]
                assert reporting.publish_publications(published) == published
                for relation in (*keys, *RAW_RELATIONS):
                    store.execute(f"DELETE FROM {relation}")
                    assert store.fetchall(f"SELECT count(*) FROM {relation}") == [(0,)]

        service = AccountTransactionService(landing_root=root / "landing",
                                            metadata_repository=RunMetadataRepository(root / "runs.db"))
        yield create_app(service, transformation_service=ts, reporting_service=reporting), today
    finally:
        store.close()
        if dsn:
            with psycopg.connect(dsn, autocommit=True) as conn:
                conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="domain-card-fixture-") as directory:
        root = Path(directory)
        scenario = os.environ["DOMAIN_CARDS_SCENARIO"]
        access = "unavailable" if scenario == "unavailable" else "published"
        if scenario == "unavailable":
            scenario = "normal"
        with domain_world(root, scenario, access=access) as (app, _):
            uvicorn.run(app, host="127.0.0.1", port=int(os.environ["DOMAIN_CARDS_API_PORT"]), log_level="warning")
