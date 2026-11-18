"""Historical-only red control: refresh old persisted stores and read strict PG.

It intentionally fails against source 82dbd947. It is not a candidate upgrade
command and does not repair schemas. It clears only disposable reporting marts,
*after* republishing, to test published-store isolation.
"""
import hashlib
import json
import os
import tempfile
from pathlib import Path

import currency_legacy_fixture
import currency_legacy_oracle
from currency_legacy_fixture import BASE, KEYS, git
from currency_legacy_oracle import assert_inventory_unchanged, snapshot_legacy_facts
from fastapi.testclient import TestClient
from test_acc_currency_separate_totals import by_currency

from apps.api.app import create_app
from packages.domains.finance.pipelines.account_transaction_service import AccountTransactionService
from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
from packages.pipelines.transformation_service import TransformationService
from packages.storage.duckdb_store import DuckDBStore
from packages.storage.postgres_reporting import PostgresReportingStore
from packages.storage.run_metadata import RunMetadataRepository

assert git("rev-parse", "HEAD") == BASE and not git("status", "--porcelain=v1", "--untracked-files=all")
manifest_path = Path(os.environ["CURRENCY_LEGACY_MANIFEST"])
warehouse = Path(os.environ["CURRENCY_LEGACY_WAREHOUSE"])
manifest = json.loads(manifest_path.read_text())
assert manifest["source_commit"] == BASE
assert hashlib.sha256(Path(currency_legacy_fixture.__file__).read_bytes()).hexdigest() == manifest["fixture_sha256"]
assert hashlib.sha256(Path(currency_legacy_oracle.__file__).read_bytes()).hexdigest() == manifest["oracle_sha256"]
assert hashlib.sha256(warehouse.read_bytes()).hexdigest() == manifest["warehouse_sha256"]
store = DuckDBStore.open(str(warehouse))
try:
    transformation = TransformationService(store)
    assert_inventory_unchanged(manifest["facts"], snapshot_legacy_facts(store, manifest["facts"]))
    transformation.refresh_publications(KEYS)
    reporting = ReportingService(transformation,
        publication_store=PostgresReportingStore(os.environ["CURRENCY_LEGACY_POSTGRES_DSN"], schema=manifest["postgres_schema"]),
        access_mode=ReportingAccessMode.PUBLISHED)
    assert reporting.publish_publications(KEYS) == KEYS
    assert_inventory_unchanged(manifest["facts"], snapshot_legacy_facts(store, manifest["facts"]))
    for key in KEYS:
        store.execute(f'DELETE FROM "{key}"')
        assert store.fetchall(f'SELECT COUNT(*) FROM "{key}"')[0][0] == 0
    assert_inventory_unchanged(manifest["facts"], snapshot_legacy_facts(store, manifest["facts"]))
    with tempfile.TemporaryDirectory(prefix="currency-legacy-red-") as folder:
        root = Path(folder)
        account = AccountTransactionService(landing_root=root / "landing", metadata_repository=RunMetadataRepository(root / "runs.db"))
        with TestClient(create_app(account, transformation_service=transformation, reporting_service=reporting)) as client:
            response = client.get("/reports/monthly-cashflow", params={"from_month": "2026-01", "to_month": "2026-01"})
            assert response.status_code == 200, response.text
            by_currency(response.json()["rows"], "net", {"EUR": 170, "USD": 80})
finally:
    store.close()
