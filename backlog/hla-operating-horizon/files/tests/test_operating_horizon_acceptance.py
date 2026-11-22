"""HTTP acceptance for the Operating Picture seven-day horizon (#1592)."""
import subprocess
from datetime import date, timedelta
from pathlib import Path

from control_plane_test_support import seed_source_asset_graph
from fastapi.testclient import TestClient

from apps.api.app import create_app
from apps.api.routes import control_routes
from packages.domains.finance.pipelines.account_transaction_service import AccountTransactionService
from packages.pipelines.reporting_service import ReportingService
from packages.pipelines.transformation_service import TransformationService
from packages.platform.action_proposals import ActionProposalRegistry
from packages.storage.duckdb_store import DuckDBStore
from packages.storage.ingestion_catalog import SourceAssetCreate, SourceFreshnessConfigCreate
from packages.storage.ingestion_config import IngestionConfigRepository
from packages.storage.run_metadata import RunMetadataRepository


def client_for(tmp_path: Path, *, reporting=None, proposals=None, config=None, admin=True):
    if reporting is None:
        reporting = ReportingService(TransformationService(DuckDBStore.memory()))
    if config is None:
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
        assert response.json()["start_date"] == date.today().isoformat()
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
    config = IngestionConfigRepository(tmp_path / "config.db")
    source = seed_source_asset_graph(config, include_lineage=False)["source_asset"]
    for source_id, name, mode, human in (
        (source.source_asset_id, source.name, "manual_export", True),
        ("automatic-pull", "Automatic pull", "api_pull", False),
    ):
        if source_id != source.source_asset_id:
            config.create_source_asset(SourceAssetCreate(
                source_asset_id=source_id, source_system_id=source.source_system_id,
                dataset_contract_id=source.dataset_contract_id,
                column_mapping_id=source.column_mapping_id, name=name, asset_type="dataset",
            ))
        config.create_source_freshness_config(SourceFreshnessConfigCreate(
            source_asset_id=source_id, acquisition_mode=mode, expected_frequency="weekly",
            coverage_kind="calendar_week", due_day_of_month=None, expected_window_days=2,
            freshness_sla_days=7, sensitivity_class="financial", reminder_channel="dashboard",
            requires_human_action=human,
        ))
    proposals = ActionProposalRegistry()
    proposals.register(policy_id="test", policy_name="Approve thermostat change",
                       verdict="review", value=None, notification_id="proposal-notification")
    dismissed = proposals.register(policy_id="resolved", policy_name="Resolved proposal",
                                    verdict="review", value=None, notification_id="resolved-notification")
    proposals.dismiss(dismissed.action_id)
    with client_for(tmp_path, reporting=reporting, proposals=proposals, config=config) as client:
        freshness = client.get("/control/source-freshness")
        assert freshness.status_code == 200, freshness.text
        assert {row["next_expected_at"][:10] for row in freshness.json()["datasets"]} == {
            today.isoformat()
        }
        response = client.get("/control/operating-horizon")
        repeated = client.get("/control/operating-horizon")
    assert response.status_code == 200, f"Operating Picture horizon feed: {response.text}"
    rows = response.json()["rows"]
    assert repeated.json()["rows"] == rows
    assert [row["date"] for row in rows] == [today.isoformat()] * 4 + [day_six.isoformat()]
    assert {(row["kind"], row["label"]) for row in rows} == {
        ("approval", "Approve thermostat change"),
        ("export", "Bank Partner Transactions"),
        ("fixed_cost", "Power bill"),
        ("fixed_cost", "Water bill"),
        ("renewal", "Energy renewal"),
    }
    assert len({row["id"] for row in rows}) == 5
    costs = [row for row in rows if row["kind"] == "fixed_cost"]
    assert [(float(row["amount"]), row["currency"]) for row in costs] == [(42, "EUR"), (23, "EUR")]


def test_operating_horizon_is_disabled_without_admin_access(tmp_path):
    with client_for(tmp_path, admin=False) as client:
        response = client.get("/control/operating-horizon")
    assert response.status_code == 404
    assert response.json()["detail"].startswith("Unsafe admin routes are disabled")

def test_operating_picture_renders_the_merged_horizon():
    result = subprocess.run(
        [
            "bash", "-c",
            'source tools/dev-env.sh && dev_prepare_env "$PWD" && '
            'node --test apps/web/frontend/unit/operating-horizon-acceptance.test.cjs',
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode not in (0, 1) or (
        result.returncode and "code: 'ERR_ASSERTION'" not in result.stdout
    ):
        raise RuntimeError(f"Horizon renderer could not be exercised: {result.stdout}{result.stderr}")
    assert result.returncode == 0, "Operating Picture did not render the merged horizon"

def test_export_evaluation_uses_the_response_start_date(tmp_path, monkeypatch):
    days = iter((date(2026, 11, 22), date(2026, 11, 23)))
    observed_dates = []

    class MidnightDate(date):
        @classmethod
        def today(cls):
            return next(days)

    def capture_views(*_, as_of, **__):
        observed_dates.append(as_of.isoformat())
        return []

    monkeypatch.setattr(control_routes, "date", MidnightDate)
    monkeypatch.setattr(control_routes, "build_source_freshness_views", capture_views)
    with client_for(tmp_path) as client:
        response = client.get("/control/operating-horizon")
    assert response.status_code == 200, response.text
    assert observed_dates == [response.json()["start_date"]], "Export dates must use the API window"
