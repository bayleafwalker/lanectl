"""Acceptance: source freshness rows list the publications that recover (#1588)."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from apps.api.app import create_app
from packages.domains.finance.pipelines.account_transaction_service import AccountTransactionService
from packages.pipelines.publication_preview import publications_for_source
from packages.storage.ingestion_config import IngestionConfigRepository
from packages.storage.run_metadata import RunMetadataRepository
from tests.account_test_support import FIXTURES as ACCOUNT_FIXTURES
from tests.control_plane_test_support import seed_source_asset_graph


def _client(temp_dir: str) -> tuple[TestClient, IngestionConfigRepository]:
    repository = IngestionConfigRepository(Path(temp_dir) / "config.db")
    seed_source_asset_graph(repository)
    client = TestClient(
        create_app(
            AccountTransactionService(
                landing_root=Path(temp_dir) / "landing",
                metadata_repository=RunMetadataRepository(Path(temp_dir) / "runs.db"),
            ),
            config_repository=repository,
            enable_unsafe_admin=True,
        )
    )
    return client, repository


def _upload_preview_keys(client: TestClient) -> list[str]:
    response = client.post(
        "/ingest/detect-source",
        files={"file": ("bank-export.csv",
                        (ACCOUNT_FIXTURES / "configured_account_transactions_source.csv").read_bytes(),
                        "text/csv")},
    )
    preview = response.json()["detection"]["candidate"]["publication_preview"]
    return [e["publication_key"] for e in preview["direct"] + preview["derived"]]


def test_stale_row_lists_the_publications_that_recover() -> None:
    with TemporaryDirectory() as temp_dir:
        client, _ = _client(temp_dir)
        (row,) = client.get("/control/source-freshness").json()["datasets"]
        assert row["freshness_state"] != "current"
        recovers = row["recovers_publications"]
        assert recovers, "a stale source holds back at least one publication"
        assert all(set(e) == {"publication_key", "name"} and e["name"] for e in recovers)
        keys = [e["publication_key"] for e in recovers]
        assert len(keys) == len(set(keys))
        assert keys == _upload_preview_keys(client)


def test_publications_for_source_matches_the_upload_preview() -> None:
    with TemporaryDirectory() as temp_dir:
        client, repository = _client(temp_dir)
        asset = next(a for a in repository.list_source_assets(include_archived=False)
                     if a.source_asset_id == "bank_partner_transactions")
        entries = publications_for_source(asset, dataset_name="household_account_transactions")
        assert [e["publication_key"] for e in entries] == _upload_preview_keys(client)


def test_publications_for_source_by_dataset_name_and_unresolvable() -> None:
    by_name = publications_for_source(None, dataset_name="account_transactions")
    assert by_name and all(e["publication_key"] and e["name"] for e in by_name)
    assert publications_for_source(None, dataset_name="zz_unknown_feed") == []
