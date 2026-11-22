"""HTTP acceptance for the Operating Picture seven-day horizon (#1592)."""
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.app import create_app
from packages.domains.finance.pipelines.account_transaction_service import AccountTransactionService
from packages.pipelines.transformation_service import TransformationService
from packages.storage.duckdb_store import DuckDBStore
from packages.storage.ingestion_config import IngestionConfigRepository
from packages.storage.run_metadata import RunMetadataRepository


def test_empty_operating_horizon_is_a_successful_read(tmp_path: Path):
    store = DuckDBStore.memory()
    config = IngestionConfigRepository(tmp_path / "config.db")
    service = AccountTransactionService(
        landing_root=tmp_path / "landing",
        metadata_repository=RunMetadataRepository(tmp_path / "runs.db"),
    )
    app = create_app(
        service,
        config_repository=config,
        transformation_service=TransformationService(store),
        enable_unsafe_admin=True,
    )
    with TestClient(app) as client:
        costs = client.get("/reports/upcoming-fixed-costs")
        assert costs.status_code == 200, costs.text
        assert costs.json()["rows"] == []
        response = client.get("/control/operating-horizon")
        assert response.status_code == 200, f"Operating Picture horizon feed: {response.text}"
        assert response.json()["rows"] == []
