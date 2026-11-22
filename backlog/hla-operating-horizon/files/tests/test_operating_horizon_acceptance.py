"""HTTP acceptance for the Operating Picture seven-day horizon (#1592)."""
from datetime import date, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.app import create_app
from packages.domains.finance.pipelines.account_transaction_service import AccountTransactionService
from packages.pipelines.transformation_service import TransformationService
from packages.pipelines.reporting_service import ReportingService
from packages.platform.action_proposals import ActionProposalRegistry
from packages.storage.duckdb_store import DuckDBStore
from packages.storage.ingestion_config import IngestionConfigRepository
from packages.storage.run_metadata import RunMetadataRepository


def client_for(tmp_path: Path, *, reporting=None, proposals=None, admin=True):
    if reporting is None:
        reporting = ReportingService(TransformationService(DuckDBStore.memory()))
    config = IngestionConfigRepository(tmp_path / "config.db")
    service = AccountTransactionService(
        landing_root=tmp_path / "landing",
        metadata_repository=RunMetadataRepository(tmp_path / "runs.db"),
    )
    app = create_app(
        service,
        config_repository=config,
        reporting_service=reporting,
        ha_action_proposal_registry=proposals,
        enable_unsafe_admin=admin,
    )
    return TestClient(app)


def test_empty_operating_horizon_is_a_successful_read(tmp_path: Path):
    with client_for(tmp_path) as client:
        costs = client.get("/reports/upcoming-fixed-costs")
        assert costs.status_code == 200, costs.text
        assert costs.json()["rows"] == []
        response = client.get("/control/operating-horizon")
        assert response.status_code == 200, f"Operating Picture horizon feed: {response.text}"
        assert response.json()["rows"] == []



def test_operating_horizon_preserves_kind_and_same_day_rows(tmp_path, monkeypatch):
    today = date.today()
    day_six = today + timedelta(days=6)
    day_seven = today + timedelta(days=7)
    reporting = ReportingService(TransformationService(DuckDBStore.memory()))
    monkeypatch.setattr(
        reporting, "get_upcoming_fixed_costs_30d",
        lambda: [
            {"contract_name": "Beyond horizon", "expected_date": day_seven},
            {"contract_name": "Water bill", "expected_date": day_six,
             "expected_amount": 23, "currency": "EUR"},
            {"contract_name": "Power bill", "expected_date": today,
             "expected_amount": 42, "currency": "EUR"},
        ],
    )
    monkeypatch.setattr(
        reporting, "get_contract_renewal_watchlist",
        lambda: [{"contract_id": "renew-1", "contract_name": "Energy renewal",
                  "provider": "Example", "renewal_date": today}],
    )
    proposals = ActionProposalRegistry()
    proposals.register(policy_id="test", policy_name="Approve thermostat change",
                       verdict="review", value=None, notification_id="proposal-notification")
    with client_for(tmp_path, reporting=reporting, proposals=proposals) as client:
        response = client.get("/control/operating-horizon")
        repeated = client.get("/control/operating-horizon")
    assert response.status_code == 200, f"Operating Picture horizon feed: {response.text}"
    rows = response.json()["rows"]
    assert repeated.json()["rows"] == rows
    assert [row["date"] for row in rows] == [today.isoformat()] * 3 + [day_six.isoformat()]
    assert {(row["kind"], row["label"]) for row in rows} == {
        ("approval", "Approve thermostat change"),
        ("fixed_cost", "Power bill"),
        ("fixed_cost", "Water bill"),
        ("renewal", "Energy renewal"),
    }
    assert len({row["id"] for row in rows}) == 4
    costs = [row for row in rows if row["kind"] == "fixed_cost"]
    assert [(float(row["amount"]), row["currency"]) for row in costs] == [(42, "EUR"), (23, "EUR")]


def test_operating_horizon_is_disabled_without_admin_access(tmp_path):
    with client_for(tmp_path, admin=False) as client:
        response = client.get("/control/operating-horizon")
    assert response.status_code == 404
    assert response.json()["detail"].startswith("Unsafe admin routes are disabled")
