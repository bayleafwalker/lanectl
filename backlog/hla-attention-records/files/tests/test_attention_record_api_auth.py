# Source-record authorization for attention item records through the real
# API auth middleware.
#
# Mode exercised: OIDC bearer tokens from MockOidcIssuer with ONLY the
# hla_permissions claim (no groups) while a reader group mapping is configured,
# so OidcProvider marks the principal permission_bound and only explicit
# publication grants apply. Machine-JWT tokens are not used for this negative
# test: authorize_request also demands the reports:read service-token scope
# for every machine_jwt principal, so a scope-less permission-only machine
# token is rejected on every /reports path, and adding a scope removes
# permission_bound. Reads use explicit ReportingAccessMode.WAREHOUSE.
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from apps.api.app import create_app
from packages.domains.finance.pipelines.account_transaction_service import (
    AccountTransactionService,
)
from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
from packages.pipelines.transformation_service import TransformationService
from packages.shared.auth import build_oidc_provider, build_session_manager
from packages.shared.settings import AppSettings
from packages.storage.duckdb_store import DuckDBStore
from packages.storage.ingestion_config import IngestionConfigRepository
from packages.storage.run_metadata import RunMetadataRepository
from tests.oidc_test_support import MockOidcIssuer
from tests.test_attention_record_api import (
    SEGMENTS,
    SOURCE_NAMES,
    record_path,
    refresh,
    seed,
    source_key,
)

ATTENTION_PERMISSION = 'reports.read.publication.attention-items'


def _permission(item_type: str) -> str:
    return 'reports.read.publication.' + SEGMENTS[item_type]


def _build(tmp_path: Path, issuer: MockOidcIssuer) -> tuple[TestClient, dict[str, str]]:
    settings = AppSettings.from_env(
        {
            'HOMELAB_ANALYTICS_DATA_DIR': str(tmp_path),
            'HOMELAB_ANALYTICS_IDENTITY_MODE': 'oidc',
            'HOMELAB_ANALYTICS_SESSION_SECRET': 'test-session-secret',
            'HOMELAB_ANALYTICS_OIDC_ISSUER_URL': issuer.issuer_url,
            'HOMELAB_ANALYTICS_OIDC_CLIENT_ID': issuer.client_id,
            'HOMELAB_ANALYTICS_OIDC_CLIENT_SECRET': issuer.client_secret,
            'HOMELAB_ANALYTICS_OIDC_REDIRECT_URI': 'http://testserver/auth/callback',
            'HOMELAB_ANALYTICS_OIDC_API_AUDIENCE': issuer.api_audience,
            'HOMELAB_ANALYTICS_OIDC_READER_GROUPS': 'readers',
            'HOMELAB_ANALYTICS_OIDC_OPERATOR_GROUPS': '',
            'HOMELAB_ANALYTICS_OIDC_ADMIN_GROUPS': '',
            'HOMELAB_ANALYTICS_OIDC_PERMISSIONS_CLAIM': 'hla_permissions',
        }
    )
    ts = TransformationService(DuckDBStore.memory())
    seed(ts)
    refresh(ts)
    reporting = ReportingService(ts, access_mode=ReportingAccessMode.WAREHOUSE)
    service = AccountTransactionService(
        landing_root=tmp_path / 'landing',
        metadata_repository=RunMetadataRepository(tmp_path / 'runs.db'),
    )
    repository = IngestionConfigRepository(tmp_path / 'config.db')
    client = TestClient(
        create_app(
            service,
            config_repository=repository,
            auth_store=repository,
            identity_mode='oidc',
            session_manager=build_session_manager(settings),
            oidc_provider=build_oidc_provider(settings, http_client=issuer.http_client()),
            transformation_service=ts,
            reporting_service=reporting,
        )
    )
    chosen: dict[str, str] = {}
    attention = reporting.get_open_attention_items()
    for item_type in SEGMENTS:
        ids = sorted(str(row['item_id']) for row in attention if row['item_type'] == item_type)
        assert ids, item_type
        slashed = [item_id for item_id in ids if '/' in item_id]
        chosen[item_type] = (slashed or ids)[0]
    assert '/' in chosen['contract_review']
    assert '/' in chosen['contract_renewal']
    return client, chosen


def _headers(issuer: MockOidcIssuer, *permissions: str) -> dict[str, str]:
    token = issuer.issue_token(
        subject='attention-reader',
        username='attention-reader@example.test',
        audience=issuer.api_audience,
        groups=(),
        extra_claims={'hla_permissions': list(permissions)},
    )
    return {'authorization': 'Bearer ' + token}


def _assert_denied(response: Any, status: int, detail: str | None = None) -> None:
    assert response.status_code == status, (response.status_code, response.text)
    body = response.json()
    assert set(body) == {'detail'}, body
    if detail is not None:
        assert body['detail'] == detail
    for name in SOURCE_NAMES:
        assert name not in response.text, (name, response.text)


def _assert_own_record(response: Any, item_type: str, item_id: str) -> None:
    assert response.status_code == 200, (item_type, item_id, response.status_code, response.text)
    body = response.json()
    assert body['item_id'] == item_id
    assert isinstance(body['rows'], list) and body['rows'], body
    assert all(source_key(item_type, row) == item_id for row in body['rows'])


def test_source_publication_permission_reads_only_its_own_segment(tmp_path: Path) -> None:
    issuer = MockOidcIssuer()
    client, ids = _build(tmp_path, issuer)
    for item_type in SEGMENTS:
        headers = _headers(issuer, ATTENTION_PERMISSION, _permission(item_type))
        assert client.get('/reports/attention-items', headers=headers).status_code == 200
        _assert_own_record(
            client.get(record_path(item_type, ids[item_type]), headers=headers),
            item_type,
            ids[item_type],
        )
        for other in SEGMENTS:
            if other == item_type:
                continue
            for item_id in (ids[other], ids[item_type]):
                _assert_denied(
                    client.get(record_path(other, item_id), headers=headers),
                    403,
                    _permission(other) + ' permission required.',
                )


def test_attention_only_permission_never_exposes_source_records(tmp_path: Path) -> None:
    issuer = MockOidcIssuer()
    client, ids = _build(tmp_path, issuer)
    attention_headers = _headers(issuer, ATTENTION_PERMISSION)
    listing = client.get('/reports/attention-items', headers=attention_headers)
    assert listing.status_code == 200, listing.text
    listed = {row['item_id'] for row in listing.json()['rows']}
    assert set(ids.values()) <= listed
    _assert_denied(
        client.get('/runs', headers=attention_headers), 403, 'runs.read permission required.'
    )
    for item_type, item_id in ids.items():
        required = _permission(item_type) + ' permission required.'
        _assert_denied(
            client.get(record_path(item_type, item_id), headers=attention_headers), 403, required
        )
        _assert_denied(
            client.get('/reports/' + SEGMENTS[item_type], headers=attention_headers), 403, required
        )
        allowed = _headers(issuer, ATTENTION_PERMISSION, _permission(item_type))
        _assert_own_record(
            client.get(record_path(item_type, item_id), headers=allowed), item_type, item_id
        )


def test_missing_or_invalid_bearer_is_rejected(tmp_path: Path) -> None:
    issuer = MockOidcIssuer()
    client, ids = _build(tmp_path, issuer)
    for item_type, item_id in ids.items():
        _assert_denied(client.get(record_path(item_type, item_id)), 401)
        _assert_denied(
            client.get(
                record_path(item_type, item_id),
                headers={'authorization': 'Bearer invalid-attention-token'},
            ),
            401,
        )
        allowed = _headers(issuer, ATTENTION_PERMISSION, _permission(item_type))
        _assert_own_record(
            client.get(record_path(item_type, item_id), headers=allowed), item_type, item_id
        )
