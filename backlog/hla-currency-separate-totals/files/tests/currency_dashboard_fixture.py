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
from test_acc_currency_separate_totals import KEYS, bill, load, usage

from apps.api.app import create_app
from packages.domains.finance.pipelines.account_transaction_service import AccountTransactionService
from packages.domains.finance.pipelines.scenario_service import ensure_scenario_storage
from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
from packages.pipelines.transformation_service import TransformationService
from packages.storage.duckdb_store import DuckDBStore
from packages.storage.postgres_reporting import PostgresReportingStore
from packages.storage.run_metadata import RunMetadataRepository


def seed_legacy_cashflows(store):
    # Save the former shapes. The income delta has a unit, but neither legacy
    # projection carries the denomination of its baseline or combined values.
    ensure_scenario_storage(store)
    for kind, key, unit, delta, income, expense in (
        ("income", "monthly_income_delta", "EUR", "20", 770, 80),
        ("expense", "expense_pct_delta", "%", "0.10", 750, 88),
    ):
        scenario_id = f"acceptance-legacy-{kind}"
        store.insert_rows("dim_scenario", [{
            "scenario_id": scenario_id, "scenario_type": "income_change" if kind == "income" else "expense_shock",
            "subject_id": "household", "label": f"Historical {kind} projection", "status": "active",
            "baseline_run_id": None, "created_at": "2025-06-01T00:00:00+00:00",
        }])
        store.insert_rows("fact_scenario_assumption", [{
            "scenario_id": scenario_id, "assumption_key": key, "baseline_value": "0",
            "override_value": delta, "unit": unit,
        }])
        store.insert_rows("proj_income_cashflow", [{
            "scenario_id": scenario_id, "period": 1, "projected_month": "2025-07",
            "baseline_income": 750, "scenario_income": income, "baseline_expense": 80,
            "scenario_expense": expense, "baseline_net": 670, "scenario_net": income - expense,
            "net_delta": income - expense - 670,
        }])


def main():
    dsn = os.environ["CURRENCY_ACCEPTANCE_POSTGRES_DSN"]
    port = int(os.environ["CURRENCY_ACCEPTANCE_HTTP_PORT"])
    schema = "currency_dashboard_" + uuid4().hex
    extra = ["mart_subscription_summary", "mart_open_attention_items", "mart_recent_significant_changes",
             "mart_affordability_ratios", "mart_recurring_cost_baseline"]
    try:
        with tempfile.TemporaryDirectory(prefix="currency-dashboard-") as folder:
            ts = TransformationService(DuckDBStore.memory())
            scenario = os.environ["CURRENCY_ACCEPTANCE_SCENARIO"]
            if scenario == "mixed":
                load(ts, [(3, "USD", 100), (1, "EUR", 200), (4, "USD", -20), (2, "EUR", -30)],
                     [bill(3, "USD", 100), bill(1, "EUR", 200)], [usage(3), usage(1)])
            elif scenario == "disjoint":
                load(ts, [(1, "USD", 250)], [bill(1, "EUR", 300)], [usage(1)])
            elif scenario in ("scenario-eur", "scenario-usd"):
                currency = "EUR" if scenario == "scenario-eur" else "USD"
                load(ts, [(1, currency, 1000), (2, currency, -100)],
                     [bill(1, currency, 100)], [usage(1)])
                seed_legacy_cashflows(ts.store)
            else:
                raise ValueError("unknown currency acceptance scenario")
            ts.refresh_publications(extra)
            reporting = ReportingService(ts, publication_store=PostgresReportingStore(dsn, schema=schema),
                                         access_mode=ReportingAccessMode.PUBLISHED)
            reporting.publish_publications(KEYS + extra)
            if scenario in ("mixed", "disjoint"):
                for key in KEYS + extra:
                    ts.store.execute(f"DELETE FROM {key}")
            else:
                # Scenario creation writes the warehouse; its follow-up API must read
                # that live store, not a publication captured before the POST.
                reporting = ReportingService(ts, access_mode=ReportingAccessMode.WAREHOUSE)
            root = Path(folder)
            service = AccountTransactionService(landing_root=root / "landing", metadata_repository=RunMetadataRepository(root / "runs.db"))
            app = create_app(service, transformation_service=ts, reporting_service=reporting)
            uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    finally:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


if __name__ == "__main__":
    main()
