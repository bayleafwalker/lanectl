"""Empty legacy currency marts must not masquerade as current valid-empty data."""
import os
from uuid import uuid4

import psycopg
from fastapi.testclient import TestClient
from psycopg import sql

from apps.api.app import create_app
from packages.domains.finance.pipelines.account_transaction_service import AccountTransactionService
from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
from packages.pipelines.transformation_service import TransformationService
from packages.storage.duckdb_store import DuckDBStore
from packages.storage.postgres_reporting import PostgresReportingStore
from packages.storage.run_metadata import RunMetadataRepository

# The original 82 monthly columns plus the denomination column required by the
# outcome. Constructing synthetic old/current tables is fixture setup, not repair.
BASE_COLUMNS = "booking_month VARCHAR NOT NULL, income DECIMAL(18,4) NOT NULL, expense DECIMAL(18,4) NOT NULL, net DECIMAL(18,4) NOT NULL, transaction_count INTEGER NOT NULL"
CURRENT_COLUMNS = BASE_COLUMNS + ", currency VARCHAR NOT NULL"
TABLE = "mart_monthly_cashflow"


def assert_refused(response):
    assert response.status_code in (409, 422, 503), (response.status_code, response.text)
    body = response.json()
    assert isinstance(body, dict) and "error" in body, body
    assert any(word in str(body["error"]).lower() for word in ("currency", "schema", "upgrade")), body


def check_empty_schema(tmp_path, *, warehouse_shape, published_shape=None):
    published = published_shape is not None
    tmp_path.mkdir(parents=True, exist_ok=True)
    store = DuckDBStore.memory()
    ts = TransformationService(store)
    service = AccountTransactionService(landing_root=tmp_path / "landing", metadata_repository=RunMetadataRepository(tmp_path / "runs.db"))
    schema = "currency_empty_" + uuid4().hex
    dsn = os.environ.get("CURRENCY_ACCEPTANCE_POSTGRES_DSN") if published else None
    if published:
        assert dsn, "A private PostgreSQL instance is required"
    try:
        # A populated warehouse can never become the strict published answer.
        store.execute(f"DROP TABLE IF EXISTS {TABLE}")
        if warehouse_shape != "absent":
            columns = BASE_COLUMNS if warehouse_shape == "legacy" else CURRENT_COLUMNS
            store.execute(f"CREATE TABLE {TABLE} ({columns})")
        if published:
            if warehouse_shape == "current":
                store.execute(f"INSERT INTO {TABLE} VALUES ('2026-01', 17, 0, 17, 1, 'USD')")
            with psycopg.connect(dsn, autocommit=True) as conn:
                conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
                if published_shape != "absent":
                    columns = BASE_COLUMNS if published_shape == "legacy" else CURRENT_COLUMNS
                    conn.execute(sql.SQL("CREATE TABLE {}.{} (" + columns + ")").format(sql.Identifier(schema), sql.Identifier(TABLE)))
            reporting = ReportingService(ts, publication_store=PostgresReportingStore(dsn, schema=schema), access_mode=ReportingAccessMode.PUBLISHED)
        else:
            reporting = ReportingService(ts, access_mode=ReportingAccessMode.WAREHOUSE)
        with TestClient(create_app(service, transformation_service=ts, reporting_service=reporting), raise_server_exceptions=False) as client:
            response = client.get("/reports/monthly-cashflow")
            if published_shape == "absent":
                assert response.status_code == 404, (response.status_code, response.text)
                assert "Published reporting relation is unavailable" in response.json()["error"]
            elif (published_shape or warehouse_shape) == "legacy":
                assert_refused(response)
            else:
                assert response.status_code == 200 and response.json()["rows"] == [], (response.status_code, response.text)
    finally:
        store.close()
        if published:
            with psycopg.connect(dsn, autocommit=True) as conn:
                conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))


def test_empty_current_warehouse_is_valid(tmp_path):
    check_empty_schema(tmp_path, warehouse_shape="current")


def test_empty_legacy_warehouse_is_refused(tmp_path):
    check_empty_schema(tmp_path, warehouse_shape="legacy")


def test_empty_current_published_is_valid(tmp_path):
    check_empty_schema(tmp_path / "nested-fixture", warehouse_shape="current", published_shape="current")


def test_empty_legacy_published_is_refused(tmp_path):
    check_empty_schema(tmp_path / "nested-fixture", warehouse_shape="current", published_shape="legacy")
