"""Mandatory independent qualification against a private PostgreSQL instance.

Run explicitly as described in QUALIFICATION.md; missing DSN is an error, not a skip.
"""
import os
from uuid import uuid4

import psycopg
from fastapi.testclient import TestClient
from test_acc_observed_backup_visibility import backup_row, utc_instant

from apps.api.app import create_app
from packages.domains.finance.pipelines.account_transaction_service import AccountTransactionService
from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
from packages.pipelines.transformation_service import TransformationService
from packages.storage.duckdb_store import DuckDBStore
from packages.storage.postgres_reporting import PostgresReportingStore
from packages.storage.run_metadata import RunMetadataRepository


def test_published_backups_survive_warehouse_clear_and_do_not_fallback(tmp_path):
    dsn = os.environ["BACKUP_ACCEPTANCE_POSTGRES_DSN"]
    schema = "backup_acceptance_" + uuid4().hex
    ts = TransformationService(DuckDBStore.memory())
    success = backup_row("success", "retrying", "success", 49, 200)
    try:
        store = PostgresReportingStore(dsn, schema=schema)
        reporting = ReportingService(ts, publication_store=store, access_mode=ReportingAccessMode.PUBLISHED)
        service = AccountTransactionService(landing_root=tmp_path / "landing", metadata_repository=RunMetadataRepository(tmp_path / "runs.db"))
        with TestClient(create_app(service, transformation_service=ts, reporting_service=reporting)) as client:
            # A valid published zero-row relation is available, not a 404.
            ts.refresh_publications(["mart_backup_freshness"])
            assert reporting.publish_publications(["mart_backup_freshness"]) == ["mart_backup_freshness"]
            empty = client.get("/api/homelab/backups")
            assert empty.status_code == 200 and empty.json()["rows"] == []

            ts.load_backup_runs([
                backup_row("latest", "failed-only", "partial", 1, 9),
                backup_row("earlier", "failed-only", "failed", 2, 0),
                success,
                backup_row("retry", "retrying", "failed", 1, 999),
                backup_row("outside", "retrying", "failed", 192, 7),
                backup_row("older", "older-only", "failed", 192, 8),
            ], run_id="published-qualification")
            ts.refresh_publications(["mart_backup_freshness"])
            reporting.publish_publications(["mart_backup_freshness"])
            ts.store.execute("DELETE FROM mart_backup_freshness")
            assert ts.store.fetchall("SELECT COUNT(*) FROM mart_backup_freshness")[0][0] == 0
            response = client.get("/api/homelab/backups")
            assert response.status_code == 200, response.text
            rows = response.json()["rows"]
            assert len(rows) == 3 and {r["target"] for r in rows} == {"failed-only", "retrying", "older-only"}, rows
            actual = {r["target"]: r for r in rows}
            failed = actual["failed-only"]
            assert failed["last_backup_at"] is None and failed["hours_since_backup"] is None
            assert failed["is_stale"] is True and failed["last_status"] == "partial" and failed["backup_count_7d"] == 2
            old = actual["older-only"]
            assert old["last_backup_at"] is None and old["hours_since_backup"] is None
            assert old["is_stale"] is True and old["last_status"] == "failed" and old["backup_count_7d"] == 0
            retry = actual["retrying"]
            assert utc_instant(retry["last_backup_at"]) == utc_instant(success["started_at"])
            assert retry["last_size_bytes"] == 200 and retry["is_stale"] is True
            assert retry["last_status"] == "failed" and retry["backup_count_7d"] == 2

            # A missing publication must not fall back even when warehouse has data.
            ts.refresh_publications(["mart_backup_freshness"])
            with psycopg.connect(dsn, autocommit=True) as conn:
                conn.execute(f'DROP TABLE "{schema}".mart_backup_freshness')
            unavailable = client.get("/api/homelab/backups")
            assert unavailable.status_code == 404, unavailable.text
            assert "Published reporting relation is unavailable" in unavailable.json()["error"]
    finally:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
