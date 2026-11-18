"""Create a private legacy currency fixture using exact HLA source 82dbd947.

This only seeds historical stores; it does not execute or choose an upgrade.
See QUALIFICATION.md for the required owner-supplied upgrade interface.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import currency_legacy_oracle
import psycopg
from currency_drift_inventory import MARTS
from currency_legacy_oracle import canonical, snapshot_legacy_facts
from fastapi.testclient import TestClient

from apps.api.app import create_app
from packages.domains.finance.pipelines.account_transaction_service import AccountTransactionService
from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
from packages.pipelines.transformation_service import TransformationService
from packages.storage.duckdb_store import DuckDBStore
from packages.storage.postgres_reporting import PostgresReportingStore
from packages.storage.run_metadata import RunMetadataRepository

BASE = "82dbd9477029d6fda7df67edc617f45a1a4ceb59"
KEYS = ["mart_monthly_cashflow", "mart_monthly_cashflow_by_counterparty", "mart_spend_by_category_monthly",
        "mart_utility_cost_summary", "mart_utility_cost_trend_monthly", "mart_household_overview"]
SNAPSHOT_KEYS = ["mart_household_overview", "mart_subscription_summary"]
EXTRA_KEYS = ["mart_subscription_summary", "mart_open_attention_items", "mart_recent_significant_changes",
              "mart_affordability_ratios", "mart_recurring_cost_baseline"]


def transactions():
    facts = [(3, "USD", 100), (1, "EUR", 200), (4, "USD", -20), (2, "EUR", -30)]
    return [{"booked_at": f"2026-01-{day:02}", "account_id": "synthetic-legacy",
             "counterparty_name": "same-counterparty", "amount": str(amount),
             "currency": currency, "description": f"legacy-{day}-{currency}"}
            for day, currency, amount in facts]


def bill(day, currency, amount):
    at = f"2026-01-{day:02}"
    return {"meter_id": "legacy-meter", "meter_name": "legacy-meter", "provider": "synthetic",
            "utility_type": "electricity", "location": "home", "billing_period_start": at,
            "billing_period_end": at, "billed_amount": str(amount), "currency": currency,
            "billed_quantity": "100", "usage_unit": "kWh", "invoice_date": at}


def usage(day):
    at = f"2026-01-{day:02}"
    return {"meter_id": "legacy-meter", "meter_name": "legacy-meter", "utility_type": "electricity",
            "location": "home", "usage_start": at, "usage_end": at,
            "usage_quantity": "100", "usage_unit": "kWh", "reading_source": "synthetic"}


def git(*argv):
    return subprocess.run(["git", *argv], check=True, capture_output=True, text=True).stdout.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--warehouse", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--drift-relation", choices=MARTS)
    args = parser.parse_args()
    keys = list(dict.fromkeys(KEYS + EXTRA_KEYS + ([args.drift_relation] if args.drift_relation else [])))
    warehouse, manifest = Path(args.warehouse), Path(args.manifest)
    if not warehouse.is_absolute() or not manifest.is_absolute() or warehouse.exists() or manifest.exists():
        sys.exit("warehouse and manifest must be new absolute paths")
    if git("rev-parse", "HEAD") != BASE or git("status", "--porcelain=v1", "--untracked-files=all"):
        sys.exit("legacy seed requires a clean checkout at the exact historical base")
    fixture_path = Path(__file__).resolve()
    oracle_path = Path(currency_legacy_oracle.__file__).resolve()
    fixture_hash = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    oracle_hash = hashlib.sha256(oracle_path.read_bytes()).hexdigest()
    dsn = os.environ["CURRENCY_LEGACY_POSTGRES_DSN"]
    schema = "currency_legacy_" + uuid4().hex
    schema_created = False
    warehouse_created = False
    manifest_created = False
    try:
        # A private random schema is reserved exclusively for this fixture.
        with psycopg.connect(dsn) as conn:
            existing = conn.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = %s", (schema,)).fetchone()
            assert existing is None
        store = DuckDBStore.open(str(warehouse))
        warehouse_created = True
        try:
            ts = TransformationService(store)
            assert ts.load_transactions(transactions(), run_id="legacy-finance") == 4
            assert ts.load_bills([bill(3, "USD", 100), bill(1, "EUR", 200)], run_id="legacy-bills") == 2
            assert ts.load_utility_usage([usage(3), usage(1)], run_id="legacy-usage") == 2
            ts.refresh_publications(keys)
            pg = PostgresReportingStore(dsn, schema=schema)
            schema_created = True
            reporting = ReportingService(ts, publication_store=pg, access_mode=ReportingAccessMode.PUBLISHED)
            assert reporting.publish_publications(keys) == keys
            assert reporting.capture_publication_snapshots(SNAPSHOT_KEYS, run_id="legacy-january", captured_at=datetime(2026, 2, 1, tzinfo=timezone.utc)) == SNAPSHOT_KEYS
            # A later fact makes January an actual past month for the existing UI.
            later = {"booked_at": "2026-02-01", "account_id": "synthetic-legacy", "counterparty_name": "later",
                     "amount": "0", "currency": "EUR", "description": "legacy-later-month"}
            assert ts.load_transactions([later], run_id="legacy-february") == 1
            ts.refresh_publications(keys)
            assert reporting.publish_publications(keys) == keys
            inventory = snapshot_legacy_facts(store)
            assert {name: len(part["rows"]) for name, part in inventory.items()} == {
                "fact_transaction": 5, "fact_bill": 2, "fact_utility_usage": 2}
            def amounts(relation, value):
                part = inventory[relation]
                return sorted((row[part["columns"].index("currency")]["value"],
                               float(row[part["columns"].index(value)]["value"])) for row in part["rows"])
            assert amounts("fact_transaction", "amount") == [("EUR", -30.0), ("EUR", 0.0), ("EUR", 200.0), ("USD", -20.0), ("USD", 100.0)]
            assert amounts("fact_bill", "billed_amount") == [("EUR", 200.0), ("USD", 100.0)]
            duck_schemas = {key: [list(row) for row in store.fetchall(f"PRAGMA table_info('{key}')")] for key in keys + ["reporting_publication_snapshot"]}
            assert "currency" not in [row[1] for row in duck_schemas["mart_monthly_cashflow"]]
            snapshot_sql = "SELECT publication_key, reference_month, captured_at, run_id, row_count, rows_json FROM reporting_publication_snapshot ORDER BY publication_key, reference_month"
            duck_snapshots = store.fetchall_dicts(snapshot_sql)
            pg_snapshots = pg.fetchall_dicts(snapshot_sql)
            assert duck_snapshots == pg_snapshots
            assert {(r["publication_key"], r["reference_month"], r["row_count"]) for r in pg_snapshots} == {
                ("mart_household_overview", "2026-01", 1), ("mart_subscription_summary", "2026-01", 0)}
            with tempfile.TemporaryDirectory(prefix="currency-legacy-api-") as temp:
                root = Path(temp)
                service = AccountTransactionService(landing_root=root / "landing", metadata_repository=RunMetadataRepository(root / "runs.db"))
                with TestClient(create_app(service, transformation_service=ts, reporting_service=reporting)) as client:
                    response = client.get("/reports/monthly-cashflow", params={"from_month": "2026-01", "to_month": "2026-01"})
                    assert response.status_code == 200, response.text
                    legacy_rows = response.json()["rows"]
                    assert len(legacy_rows) == 1 and float(legacy_rows[0]["net"]) == 250
                    assert "currency" not in legacy_rows[0]
                    snapshot = client.get("/reports/household-overview", params={"as_of": "2026-01"})
                    assert snapshot.status_code == 200 and snapshot.json()["as_of_status"] == "snapshot"
                    assert snapshot.json()["snapshot"]["run_id"] == "legacy-january"
                    empty = client.get("/reports/subscription-summary", params={"as_of": "2026-01"})
                    assert empty.status_code == 200 and empty.json()["as_of_status"] == "snapshot" and empty.json()["rows"] == []
            with psycopg.connect(dsn) as conn:
                pg_schemas = {}
                for key in keys + ["reporting_publication_snapshot"]:
                    cols = conn.execute("SELECT column_name, data_type, is_nullable, ordinal_position FROM information_schema.columns WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position", (schema, key)).fetchall()
                    assert cols, key
                    pg_schemas[key] = [list(row) for row in cols]
            assert "currency" not in [row[0] for row in pg_schemas["mart_monthly_cashflow"]]
            pg_rows = {}
            for key in [*KEYS, *([args.drift_relation] if args.drift_relation and args.drift_relation not in KEYS else [])]:
                captured = [{column: canonical(value) for column, value in row.items()}
                            for row in pg.fetchall_dicts(f'SELECT * FROM "{key}"')]
                pg_rows[key] = sorted(captured, key=lambda row: json.dumps(row, sort_keys=True))
        finally:
            store.close()
        if git("rev-parse", "HEAD") != BASE or git("status", "--porcelain=v1", "--untracked-files=all"):
            raise RuntimeError("historical source changed during legacy seed")
        if (hashlib.sha256(fixture_path.read_bytes()).hexdigest() != fixture_hash
                or hashlib.sha256(oracle_path.read_bytes()).hexdigest() != oracle_hash):
            raise RuntimeError("legacy fixture or oracle changed during seed; evidence rejected")
        record = {"kind": "hla-currency-legacy-fixture/v2", "source_commit": BASE,
                  "fixture_sha256": fixture_hash,
                  "oracle_sha256": oracle_hash,
                  "warehouse_sha256": hashlib.sha256(warehouse.read_bytes()).hexdigest(),
                  "postgres_schema": schema, "duckdb_schemas": duck_schemas,
                  "postgres_schemas": pg_schemas, "postgres_rows": pg_rows, "facts": inventory,
                  "legacy_snapshots": {"duckdb": duck_snapshots, "postgres": pg_snapshots},
                  "legacy_published_finance_rows": legacy_rows, "drift_relation": args.drift_relation}
        with manifest.open("x") as output:
            manifest_created = True
            output.write(json.dumps(record, indent=2) + "\n")
        print(f"Legacy fixture ready: manifest={manifest} schema={schema}; private warehouse={warehouse}")
    except BaseException:
        if schema_created:
            with psycopg.connect(dsn, autocommit=True) as conn:
                conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        if warehouse_created:
            warehouse.unlink(missing_ok=True)
        if manifest_created:
            manifest.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    main()
