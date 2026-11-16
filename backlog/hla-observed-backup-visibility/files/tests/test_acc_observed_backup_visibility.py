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


def utc_instant(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def test_observation_window_and_attempt_order(tmp_path):
    with backup_api(tmp_path) as (transformation, client):
        rows = [
            backup_row("new", "ordered", "partial", 1, 4),
            backup_row("old", "ordered", "failed", 192, 5),
            backup_row("middle", "ordered", "failed", 2, 6),
            backup_row("only-old", "older-only", "failed", 192, 7),
        ]
        transformation.load_backup_runs(rows, run_id="window-order")
        actual = read_backups(transformation, client)
        assert set(actual) == {"ordered", "older-only"}
        assert actual["ordered"]["last_status"] == "partial"
        assert actual["ordered"]["backup_count_7d"] == 2
        assert actual["older-only"]["backup_count_7d"] == 0
        assert actual["older-only"]["last_status"] == "failed"
        assert actual["older-only"]["last_backup_at"] is None
        assert actual["older-only"]["hours_since_backup"] is None
        assert actual["older-only"]["is_stale"] is True


def test_latest_success_uses_its_started_at_and_size(tmp_path):
    with backup_api(tmp_path) as (transformation, client):
        latest_success = backup_row("success-later", "target", "success", 3, 321)
        transformation.load_backup_runs([
            latest_success,
            backup_row("success-earlier", "target", "success", 6, 123),
            backup_row("failure-latest", "target", "failed", 1, 999),
        ], run_id="success-source")
        actual = read_backups(transformation, client)["target"]
        assert utc_instant(actual["last_backup_at"]) == utc_instant(latest_success["started_at"])
        assert actual["last_size_bytes"] == 321
        assert actual["is_stale"] is False
        assert actual["last_status"] == "failed"


def test_added_oracles_reject_wrong_window_order_timestamp_and_size(tmp_path, monkeypatch):
    """Exercise each added assertion with synthetic good and wrong API rows."""
    import copy
    import sys
    import pytest

    loaded = []
    class FakeTransformation:
        def load_backup_runs(self, rows, **_):
            loaded.extend(rows)

    @contextmanager
    def fake_api(_root):
        loaded.clear()
        yield FakeTransformation(), object()

    module = sys.modules[__name__]
    monkeypatch.setattr(module, "backup_api", fake_api)

    def window_rows(*_):
        return {
            "ordered": {"last_status": "partial", "backup_count_7d": 2},
            "older-only": {"last_status": "failed", "backup_count_7d": 0,
                           "last_backup_at": None, "hours_since_backup": None, "is_stale": True},
        }

    monkeypatch.setattr(module, "read_backups", window_rows)
    test_observation_window_and_attempt_order(tmp_path)
    for target, field, wrong in [("ordered", "last_status", "failed"),
                                 ("ordered", "backup_count_7d", 3),
                                 ("older-only", "backup_count_7d", 1)]:
        def mutated(*_, target=target, field=field, wrong=wrong):
            rows = copy.deepcopy(window_rows())
            rows[target][field] = wrong
            return rows
        monkeypatch.setattr(module, "read_backups", mutated)
        with pytest.raises(AssertionError):
            test_observation_window_and_attempt_order(tmp_path)

    def success_rows(*_):
        return {"target": {"last_backup_at": loaded[0]["started_at"],
                           "last_size_bytes": 321, "is_stale": False, "last_status": "failed"}}
    monkeypatch.setattr(module, "read_backups", success_rows)
    test_latest_success_uses_its_started_at_and_size(tmp_path)
    for field in ("last_backup_at", "last_size_bytes"):
        def mutated(*_, field=field):
            rows = copy.deepcopy(success_rows())
            rows["target"][field] = loaded[0]["completed_at"] if field == "last_backup_at" else 123
            return rows
        monkeypatch.setattr(module, "read_backups", mutated)
        with pytest.raises(AssertionError):
            test_latest_success_uses_its_started_at_and_size(tmp_path)
