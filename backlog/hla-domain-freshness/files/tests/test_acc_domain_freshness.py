"""Acceptance: domain freshness aggregation in the platform (#1553)."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

import apps.api.routes.control_routes as control_routes
from apps.api.app import create_app
from packages.domains.finance.pipelines.account_transaction_service import AccountTransactionService
from packages.platform.domain_freshness import (
    domain_for_package,
    is_stale_publication,
    summarize_domains,
    worst_case_verdict,
)
from packages.storage.ingestion_config import IngestionConfigRepository
from packages.storage.run_metadata import RunMetadataRepository
from tests.control_plane_test_support import seed_source_asset_graph


def test_domain_labels():
    assert domain_for_package(None) == "platform" and domain_for_package("") == "platform"
    assert domain_for_package("builtin_account_transactions") == "finance"
    assert domain_for_package("builtin_utility_usage") == "utilities"
    assert domain_for_package("builtin_homelab") == "homelab"
    assert domain_for_package("builtin_household_overview") == "overview"
    assert domain_for_package("builtin_garden_sensors") == "garden sensors"


def test_verdict_and_staleness_helpers():
    assert worst_case_verdict("trustworthy", "degraded") == "degraded"
    assert worst_case_verdict("unavailable", "unreliable") == "unavailable"
    assert is_stale_publication("stale") and is_stale_publication("UNAVAILABLE")
    assert not is_stale_publication("current") and not is_stale_publication("due_soon")


def test_summarize_two_non_finance_domains():
    rows = [
        {"domain": "utilities", "confidence_verdict": "trustworthy", "freshness_state": "current"},
        {"domain": "utilities", "confidence_verdict": "degraded", "freshness_state": "stale"},
        {"domain": "homelab", "confidence_verdict": "unavailable", "freshness_state": "unavailable"},
        {"domain": "homelab", "confidence_verdict": "Trustworthy", "freshness_state": "due_soon"},
    ]
    assert summarize_domains(rows) == [
        {"domain": "homelab", "verdict": "unavailable", "count": 2, "degraded_count": 1,
         "stale_count": 1},
        {"domain": "utilities", "verdict": "degraded", "count": 2, "degraded_count": 1,
         "stale_count": 1},
    ]
    assert summarize_domains([]) == []


def test_route_module_keeps_no_private_copies():
    for name in ("_publication_domain", "_worst_case_verdict", "_is_stale_publication"):
        assert not hasattr(control_routes, name), name


def _client(temp_dir: str) -> TestClient:
    repository = IngestionConfigRepository(Path(temp_dir) / "config.db")
    seed_source_asset_graph(repository)
    return TestClient(create_app(
        AccountTransactionService(
            landing_root=Path(temp_dir) / "landing",
            metadata_repository=RunMetadataRepository(Path(temp_dir) / "runs.db"),
        ),
        config_repository=repository,
        enable_unsafe_admin=True,
    ))


def test_source_freshness_rows_carry_domain():
    with TemporaryDirectory() as temp_dir:
        (row,) = _client(temp_dir).get("/control/source-freshness").json()["datasets"]
        assert row["dataset_name"] == "household_account_transactions"
        assert row["domain"] == "finance"


def test_confidence_route_summaries_match_the_platform_function():
    with TemporaryDirectory() as temp_dir:
        body = _client(temp_dir).get("/control/confidence").json()
        assert body["domain_summaries"] == summarize_domains(body["publications"])
