"""Historical-only red control for denomination-ambiguous snapshot status."""
import hashlib
import json
import os
import tempfile
from pathlib import Path

import currency_legacy_fixture
import currency_legacy_oracle
from currency_legacy_fixture import BASE, git
from fastapi.testclient import TestClient
from test_acc_currency_legacy_upgrade import history_unavailable

from apps.api.app import create_app
from packages.domains.finance.pipelines.account_transaction_service import AccountTransactionService
from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
from packages.pipelines.transformation_service import TransformationService
from packages.storage.duckdb_store import DuckDBStore
from packages.storage.postgres_reporting import PostgresReportingStore
from packages.storage.run_metadata import RunMetadataRepository

assert git("rev-parse", "HEAD") == BASE and not git("status", "--porcelain=v1", "--untracked-files=all")
manifest = json.loads(Path(os.environ["CURRENCY_LEGACY_MANIFEST"]).read_text())
warehouse = Path(os.environ["CURRENCY_LEGACY_WAREHOUSE"])
assert manifest["source_commit"] == BASE
assert hashlib.sha256(Path(currency_legacy_fixture.__file__).read_bytes()).hexdigest() == manifest["fixture_sha256"]
assert hashlib.sha256(Path(currency_legacy_oracle.__file__).read_bytes()).hexdigest() == manifest["oracle_sha256"]
assert hashlib.sha256(warehouse.read_bytes()).hexdigest() == manifest["warehouse_sha256"]
store = DuckDBStore.open(str(warehouse))
try:
    transformation = TransformationService(store)
    reporting = ReportingService(transformation,
        publication_store=PostgresReportingStore(os.environ["CURRENCY_LEGACY_POSTGRES_DSN"], schema=manifest["postgres_schema"]),
        access_mode=ReportingAccessMode.PUBLISHED)
    with tempfile.TemporaryDirectory(prefix="currency-legacy-history-red-") as folder:
        root = Path(folder)
        service = AccountTransactionService(landing_root=root / "landing", metadata_repository=RunMetadataRepository(root / "runs.db"))
        with TestClient(create_app(service, transformation_service=transformation, reporting_service=reporting)) as client:
            response = client.get("/reports/household-overview", params={"as_of": "2026-01"})
            assert response.status_code == 200, response.text
            history_unavailable(response.json())
finally:
    store.close()
