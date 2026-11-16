"""Independent observed-backup visibility and latest-attempt contract oracle."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from apps.api.app import create_app
from packages.domains.finance.pipelines.account_transaction_service import AccountTransactionService
from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
from packages.pipelines.transformation_service import TransformationService
from packages.storage.duckdb_store import DuckDBStore
from packages.storage.run_metadata import RunMetadataRepository


@contextmanager
def backup_api(root, *, unavailable=False):
    root.mkdir(parents=True, exist_ok=True)
    transformation = TransformationService(DuckDBStore.memory())
    service = AccountTransactionService(
        landing_root=root / "landing",
        metadata_repository=RunMetadataRepository(root / "runs.db"),
    )
    reporting = (
        ReportingService(transformation, access_mode=ReportingAccessMode.PUBLISHED)
        if unavailable else None
    )
    with TestClient(create_app(
        service, transformation_service=transformation, reporting_service=reporting
    )) as client:
        yield transformation, client


def backup_row(identity, target, status, hours, size):
    at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
    return {
        "backup_id": identity, "target": target, "status": status,
        "started_at": at.isoformat(),
        "completed_at": (at + timedelta(minutes=5)).isoformat(),
        "size_bytes": str(size),
    }


def read_backups(transformation, client):
    transformation.refresh_publications(["mart_backup_freshness"])
    response = client.get("/api/homelab/backups")
    assert response.status_code == 200, response.text
    return {row["target"]: row for row in response.json()["rows"]}


def test_never_successful_observed_target_is_visible(tmp_path):
    with backup_api(tmp_path) as (transformation, client):
        assert transformation.load_backup_runs([
            backup_row("a", "failed-only", "failed", 2, 0),
            backup_row("b", "failed-only", "partial", 1, 15),
        ], run_id="observed-failures") == 2
        actual = read_backups(transformation, client)
        assert set(actual) == {"failed-only"}, f"observed target omitted: {actual}"
        result = actual["failed-only"]
        assert result["last_backup_at"] is None
        assert result["hours_since_backup"] is None
        assert result["is_stale"] is True
        assert result["last_status"] == "partial"
        assert result["backup_count_7d"] == 2


def test_latest_attempt_status_preserves_successful_recovery_point(tmp_path):
    with backup_api(tmp_path) as (transformation, client):
        transformation.load_backup_runs([
            backup_row("s", "retrying", "success", 49, 200)
        ], run_id="success")
        before = read_backups(transformation, client)["retrying"]
        assert before["is_stale"] is True
        transformation.load_backup_runs([
            backup_row("f", "retrying", "failed", 1, 999)
        ], run_id="failed-retry")
        after = read_backups(transformation, client)["retrying"]
        for name in ("target", "last_backup_at", "last_size_bytes", "is_stale"):
            assert after[name] == before[name], name
        assert float(after["hours_since_backup"]) >= 24
        assert after["backup_count_7d"] == 2
        assert after["last_status"] == "failed", after


def test_existing_24_hour_success_freshness_controls(tmp_path):
    with backup_api(tmp_path) as (transformation, client):
        transformation.load_backup_runs([
            backup_row("a", "younger", "success", 23, 100),
            backup_row("b", "older", "success", 25, 200),
        ], run_id="controls")
        actual = read_backups(transformation, client)
        assert set(actual) == {"younger", "older"}
        assert actual["younger"]["is_stale"] is False
        assert actual["older"]["is_stale"] is True
        assert actual["younger"]["last_size_bytes"] == 100
        assert actual["older"]["last_size_bytes"] == 200


def test_empty_publication_is_distinct_from_unavailable(tmp_path):
    with backup_api(tmp_path / "empty") as (transformation, client):
        assert read_backups(transformation, client) == {}
    with backup_api(tmp_path / "unavailable", unavailable=True) as (_, client):
        response = client.get("/api/homelab/backups")
        assert response.status_code == 404
        assert "Published reporting relation is unavailable" in response.json()["error"]
