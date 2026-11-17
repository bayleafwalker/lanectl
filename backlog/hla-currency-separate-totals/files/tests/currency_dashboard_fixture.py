"""Serve the synthetic currency fixture from real strict-PUBLISHED reporting.

This is an owner-run local qualification helper, not a product server or mock.
CURRENCY_ACCEPTANCE_POSTGRES_DSN must name an isolated disposable instance.
"""
import os
import tempfile
from pathlib import Path
from uuid import uuid4

import psycopg
import uvicorn

from apps.api.app import create_app
from packages.domains.finance.pipelines.account_transaction_service import AccountTransactionService
from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
from packages.pipelines.transformation_service import TransformationService
from packages.storage.duckdb_store import DuckDBStore
from packages.storage.postgres_reporting import PostgresReportingStore
from packages.storage.run_metadata import RunMetadataRepository
from test_acc_currency_separate_totals import KEYS, bill, load, usage


def main():
    dsn = os.environ["CURRENCY_ACCEPTANCE_POSTGRES_DSN"]
    port = int(os.environ["CURRENCY_ACCEPTANCE_HTTP_PORT"])
    schema = "currency_dashboard_" + uuid4().hex
    extra = ["mart_subscription_summary", "mart_open_attention_items", "mart_recent_significant_changes",
             "mart_affordability_ratios", "mart_recurring_cost_baseline"]
    try:
        with tempfile.TemporaryDirectory(prefix="currency-dashboard-") as folder:
            ts = TransformationService(DuckDBStore.memory())
            load(ts, [(3, "USD", 100), (1, "EUR", 200), (4, "USD", -20), (2, "EUR", -30)],
                 [bill(3, "USD", 100), bill(1, "EUR", 200)], [usage(3), usage(1)])
            ts.refresh_publications(extra)
            reporting = ReportingService(ts, publication_store=PostgresReportingStore(dsn, schema=schema),
                                         access_mode=ReportingAccessMode.PUBLISHED)
            reporting.publish_publications(KEYS + extra)
            for key in KEYS + extra:
                ts.store.execute(f"DELETE FROM {key}")
            root = Path(folder)
            service = AccountTransactionService(landing_root=root / "landing", metadata_repository=RunMetadataRepository(root / "runs.db"))
            app = create_app(service, transformation_service=ts, reporting_service=reporting)
            uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    finally:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


if __name__ == "__main__":
    main()
