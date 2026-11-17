"""Mandatory real-PostgreSQL published currency qualification; no skips."""
import os
from uuid import uuid4

import psycopg
from fastapi.testclient import TestClient

from apps.api.app import create_app
from packages.domains.finance.pipelines.account_transaction_service import AccountTransactionService
from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
from packages.pipelines.transformation_service import TransformationService
from packages.storage.duckdb_store import DuckDBStore
from packages.storage.postgres_reporting import PostgresReportingStore
from packages.storage.run_metadata import RunMetadataRepository
from test_acc_currency_separate_totals import KEYS, assert_disjoint_household_contributions, bill, by_currency, load, rows, usage


def test_currency_published_reporting_survives_warehouse_clear_without_fallback(tmp_path):
    dsn = os.environ["CURRENCY_ACCEPTANCE_POSTGRES_DSN"]
    schema = "currency_acceptance_" + uuid4().hex
    ts = TransformationService(DuckDBStore.memory())
    try:
        store = PostgresReportingStore(dsn, schema=schema)
        reporting = ReportingService(ts, publication_store=store, access_mode=ReportingAccessMode.PUBLISHED)
        service = AccountTransactionService(landing_root=tmp_path / "landing", metadata_repository=RunMetadataRepository(tmp_path / "runs.db"))
        with TestClient(create_app(service, transformation_service=ts, reporting_service=reporting)) as client:
            ts.refresh_publications(KEYS)
            reporting.publish_publications(KEYS)
            assert rows(client, "/reports/monthly-cashflow") == []
            load(ts, [(3, "USD", 100), (1, "EUR", 200), (4, "USD", -20), (2, "EUR", -30)],
                 [bill(3, "USD", 100), bill(1, "EUR", 200)], [usage(3), usage(1)])
            assert reporting.publish_publications(KEYS) == KEYS
            for key in KEYS:
                ts.store.execute(f"DELETE FROM {key}")
                assert ts.store.fetchall(f"SELECT COUNT(*) FROM {key}")[0][0] == 0
            by_currency(rows(client, "/reports/monthly-cashflow"), "net", {"EUR": 170, "USD": 80})
            by_currency(rows(client, "/reports/monthly-cashflow-by-counterparty"), "net", {"EUR": 170, "USD": 80})
            by_currency(rows(client, "/reports/spend-by-category-monthly"), "total_expense", {"EUR": 30, "USD": 20})
            by_currency(rows(client, "/reports/utility-cost-summary"), "billed_amount", {"EUR": 200, "USD": 100})
            trend = rows(client, "/reports/utility-cost-trend")
            by_currency(trend, "total_cost", {"EUR": 200, "USD": 100})
            by_currency(trend, "unit_price_effective", {"EUR": 2, "USD": 1})
            by_currency(rows(client, "/reports/household-overview"), "cashflow_net", {"EUR": 170, "USD": 80})
            for path in ("/api/ha/metrics/current-month/net-cashflow", "/api/ha/metrics/current-month/electricity-cost"):
                response = client.get(path)
                assert response.status_code == 200 and response.json() == {"value": None, "unit": ""}
            ts.refresh_publications(KEYS)
            with psycopg.connect(dsn, autocommit=True) as conn:
                conn.execute(f'DROP TABLE "{schema}".mart_monthly_cashflow')
            unavailable = client.get("/reports/monthly-cashflow")
            assert unavailable.status_code == 404
            assert "Published reporting relation is unavailable" in unavailable.json()["error"]
        disjoint = TransformationService(DuckDBStore.memory())
        load(disjoint, [(1, "USD", 250)], [bill(1, "EUR", 300)], [usage(1)])
        published = ReportingService(disjoint, publication_store=store, access_mode=ReportingAccessMode.PUBLISHED)
        published.publish_publications(KEYS)
        for key in KEYS:
            disjoint.store.execute(f"DELETE FROM {key}")
        with TestClient(create_app(service, transformation_service=disjoint, reporting_service=published)) as client:
            assert_disjoint_household_contributions(rows(client, "/reports/household-overview"))
    finally:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
