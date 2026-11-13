# Attention item -> source record reads through the real API router.
#
# Modes exercised by this portable file (no Docker or Postgres needed):
# - ReportingAccessMode.WAREHOUSE, selected explicitly.
# - ReportingAccessMode.PUBLISHED, selected explicitly, over a DuckDB-backed
#   publication store adapter that runs the reporting layer's real
#   parameterized SQL (%s placeholders become DuckDB ? placeholders). The
#   adapter never returns canned rows.
# The function-marked slow case exercises disposable Postgres.
#
# Record contract frozen here:
#   GET /reports/<source segment>/records/<url-encoded attention item_id>
#   200 -> {item_id, rows: [existing public source row model]}
#   404 -> provably unknown key (safe JSON detail, no rows)
#   503 -> PUBLISHED source publication missing, or identity fields NULL so
#          absence cannot be established
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from apps.api.app import create_app
from packages.domains.finance.pipelines.account_transaction_service import (
    AccountTransactionService,
)
from packages.domains.finance.pipelines.subscription_models import subscription_charge_id
from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
from packages.pipelines.transformation_service import TransformationService
from packages.storage.duckdb_store import DuckDBStore
from packages.storage.run_metadata import RunMetadataRepository

from packages.shared.auth import build_oidc_provider, build_session_manager
from packages.shared.settings import AppSettings
from packages.storage.ingestion_config import IngestionConfigRepository
from packages.storage.postgres_reporting import PostgresReportingStore
from tests.oidc_test_support import MockOidcIssuer
from tests.postgres_test_support import running_postgres_container

REPO_ROOT = Path(__file__).resolve().parents[1]

SEGMENTS: dict[str, str] = {
    'anomaly': 'transaction-anomalies',
    'contract_review': 'contract-review-candidates',
    'contract_renewal': 'contract-renewal-watchlist',
    'upcoming_cost': 'upcoming-fixed-costs',
}
ROW_MODELS: dict[str, str] = {
    'anomaly': 'TransactionAnomaliesRow',
    'contract_review': 'ContractReviewCandidatesRow',
    'contract_renewal': 'ContractRenewalWatchlistRow',
    'upcoming_cost': 'UpcomingFixedCostsRow',
}
SOURCE_RELATIONS = [
    'mart_transaction_anomalies_current',
    'mart_contract_review_candidates',
    'mart_contract_renewal_watchlist',
    'mart_upcoming_fixed_costs_30d',
]
ATTENTION_RELATION = 'mart_open_attention_items'
REFRESH_KEYS = [
    'mart_subscription_summary',
    'mart_upcoming_fixed_costs_30d',
    'mart_contract_price_current',
    'mart_contract_review_candidates',
    'mart_contract_renewal_watchlist',
    'mart_transaction_anomalies_current',
    'mart_open_attention_items',
]
VENDOR_COUNT = 240
SOURCE_NAMES = (
    'NorthPower',
    'StreamCo',
    'Streamly',
    'Vendor ',
    'Regular Grocer',
    'Late Vendor',
    'Grid Plan',
)
QUOTE = chr(39)


class DuckPublicationStore:
    # Publication store adapter over a separate DuckDB database. It executes
    # the reporting layer's own SQL; nothing here knows the expected rows.

    def __init__(self) -> None:
        self.store = DuckDBStore.memory()

    @staticmethod
    def _sql(statement: Any) -> str:
        text = statement if isinstance(statement, str) else statement.as_string(None)
        return text.replace('%%', '<<pct>>').replace('%s', '?').replace('<<pct>>', '%')

    def table_exists(self, table_name: str) -> bool:
        rows = self.store.fetchall(
            'SELECT 1 FROM information_schema.tables WHERE table_name = ?',
            [table_name],
        )
        return bool(rows)

    def ensure_table(self, table_name: str, columns: list[tuple[str, str]]) -> None:
        self.store.ensure_table(table_name, columns)

    def replace_rows(
        self,
        table_name: str,
        columns: list[tuple[str, str]],
        rows: list[dict[str, Any]],
    ) -> None:
        self.ensure_table(table_name, columns)
        names = [name for name, _ in columns]
        self.store.execute('DELETE FROM ' + table_name)
        if rows:
            self.store.connection.executemany(
                'INSERT INTO ' + table_name + ' (' + ', '.join(names) + ') VALUES ('
                + ', '.join('?' for _ in names) + ')',
                [[row.get(name) for name in names] for row in rows],
            )

    def fetchall_dicts(self, sql: Any, params: Any = None) -> list[dict[str, Any]]:
        return self.store.fetchall_dicts(self._sql(sql), list(params or []))

    def execute_statements(self, statements: list[tuple[Any, Any]]) -> None:
        with self.store.atomic():
            for sql, params in statements:
                self.store.execute(self._sql(sql), list(params or []))


def _price(
    contract_id: str,
    component: str,
    unit_price: str,
    valid_to: date,
    today: date,
) -> dict[str, Any]:
    return {
        'contract_id': contract_id,
        'contract_name': 'Grid Plan ' + contract_id,
        'provider': 'NorthPower',
        'contract_type': 'electricity',
        'price_component': component,
        'billing_cycle': 'monthly',
        'unit_price': unit_price,
        'currency': 'EUR',
        'quantity_unit': 'kWh',
        'valid_from': str(today - timedelta(days=400)),
        'valid_to': str(valid_to),
    }


def seed(ts: TransformationService) -> dict[str, Any]:
    today = ts.store.fetchall('SELECT CURRENT_DATE')[0][0]
    # Seven days apart: same next weekly occurrence, same visible name/amount,
    # but distinct canonical charge identities.
    starts = [today - timedelta(days=14), today - timedelta(days=7)]
    ts.load_subscriptions(
        [
            {
                'contract_id': 'sub-stream',
                'service_name': 'Streamly',
                'provider': 'StreamCo',
                'billing_cycle': 'weekly',
                'amount': '12.50',
                'currency': 'EUR',
                'start_date': str(start),
                'end_date': None,
            }
            for start in starts
        ],
        run_id='subscriptions',
    )
    d10 = today + timedelta(days=10)
    d20 = today + timedelta(days=20)
    # Contract ids exercise a slash and underscore prefixes of each other.
    # Average electricity price is 1.6, so the 2 and 3 components of
    # grid/north are above_market_average; the rest are
    # multiple_contracts_same_type.
    ts.load_contract_prices(
        [
            _price('grid/north', 'energy', '1', d10, today),
            _price('grid/north', 'transfer', '2', d10, today),
            _price('grid/north', 'tax', '3', d20, today),
            _price('grid', 'energy', '1', d10, today),
            _price('grid_north', 'energy', '1', d20, today),
        ],
        run_id='prices',
    )
    transactions = [
        {
            'booked_at': str(today),
            'account_id': 'bank',
            'counterparty_name': 'Vendor ' + str(index).zfill(3),
            'amount': '-' + str(100 + index),
            'currency': 'EUR',
            'description': 'purchase',
        }
        for index in range(VENDOR_COUNT)
    ]
    transactions += [
        {
            'booked_at': str(today - timedelta(days=days)),
            'account_id': 'bank',
            'counterparty_name': 'Regular Grocer',
            'amount': '-10',
            'currency': 'EUR',
            'description': 'groceries ' + str(days),
        }
        for days in (1, 2, 3)
    ]
    ts.load_transactions(transactions, run_id='transactions')
    return {
        'today': today,
        'charge_ids': sorted(
            subscription_charge_id('Streamly', 'weekly', str(start)) for start in starts
        ),
        'd10': str(d10),
        'd20': str(d20),
    }


def refresh(ts: TransformationService) -> None:
    ts.refresh_publications(REFRESH_KEYS)


def publish(ts: TransformationService, store: Any) -> None:
    keys = [*SOURCE_RELATIONS, ATTENTION_RELATION]
    published = ReportingService(ts, publication_store=store).publish_publications(keys)
    assert published == keys


def regular_transaction_keys(ts: TransformationService) -> list[str]:
    rows = ts.store.fetchall(
        'SELECT entity_key FROM fact_transaction_current WHERE counterparty_name = ?',
        ['Regular Grocer'],
    )
    return sorted(str(row[0]) for row in rows)


def make_client(
    tmp_path: Path,
    ts: TransformationService,
    reporting: ReportingService,
    *,
    name: str = 'app',
) -> TestClient:
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    service = AccountTransactionService(
        landing_root=root / 'landing',
        metadata_repository=RunMetadataRepository(root / 'runs.db'),
    )
    return TestClient(
        create_app(service, transformation_service=ts, reporting_service=reporting)
    )


@dataclass
class World:
    client: TestClient
    ts: TransformationService
    store: DuckPublicationStore | None
    facts: dict[str, Any]
    mode: str


def build_world(tmp_path: Path, mode: str) -> World:
    ts = TransformationService(DuckDBStore.memory())
    facts = seed(ts)
    refresh(ts)
    store: DuckPublicationStore | None = None
    if mode == 'warehouse':
        reporting = ReportingService(ts, access_mode=ReportingAccessMode.WAREHOUSE)
    else:
        store = DuckPublicationStore()
        publish(ts, store)
        reporting = ReportingService(
            ts,
            publication_store=store,  # type: ignore[arg-type]
            access_mode=ReportingAccessMode.PUBLISHED,
        )
    return World(make_client(tmp_path, ts, reporting, name=mode), ts, store, facts, mode)


@pytest.fixture(params=['warehouse', 'published'])
def world(request: pytest.FixtureRequest, tmp_path: Path) -> World:
    return build_world(tmp_path, request.param)


def source_key(item_type: str, row: dict[str, Any]) -> str:
    if item_type == 'anomaly':
        return 'anomaly_' + str(row['transaction_id'])
    if item_type == 'contract_review':
        return 'review_' + str(row['contract_id']) + '_' + str(row['reason'])
    if item_type == 'contract_renewal':
        return 'renewal_' + str(row['contract_id']) + '_' + str(row['renewal_date'])
    return 'upcoming_' + str(row['charge_id']) + '_' + str(row['expected_date'])


def record_path(item_type: str, item_id: str) -> str:
    return '/reports/' + SEGMENTS[item_type] + '/records/' + quote(item_id, safe='')


def get_record(client: TestClient, item_type: str, item_id: str, headers: Any = None) -> Any:
    return client.get(record_path(item_type, item_id), headers=headers or {})


def list_rows(client: TestClient, item_type: str) -> list[dict[str, Any]]:
    response = client.get('/reports/' + SEGMENTS[item_type])
    assert response.status_code == 200, response.text
    return response.json()['rows']


def expected_records(client: TestClient) -> dict[tuple[str, str], list[dict[str, Any]]]:
    expected: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item_type in SEGMENTS:
        for row in list_rows(client, item_type):
            expected.setdefault((item_type, source_key(item_type, row)), []).append(row)
    return expected


def attention_by_type(client: TestClient) -> dict[str, list[str]]:
    response = client.get('/reports/attention-items')
    assert response.status_code == 200, response.text
    grouped: dict[str, list[str]] = {item_type: [] for item_type in SEGMENTS}
    for row in response.json()['rows']:
        grouped[row['item_type']].append(row['item_id'])
    return grouped


def canon(rows: list[dict[str, Any]]) -> list[str]:
    return sorted(json.dumps(row, sort_keys=True) for row in rows)


def get_rows(client: TestClient, item_type: str, item_id: str) -> list[dict[str, Any]]:
    response = get_record(client, item_type, item_id)
    assert response.status_code == 200, (item_type, item_id, response.status_code, response.text)
    body = response.json()
    assert set(body) == {'item_id', 'rows'}, body
    assert body['item_id'] == item_id
    assert set(body) == {'item_id', 'rows'}, body
    assert isinstance(body['rows'], list) and body['rows'], body
    return body['rows']


def assert_resolves(
    client: TestClient,
    item_type: str,
    item_id: str,
    expected_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    assert expected_rows, (item_type, item_id)
    rows = get_rows(client, item_type, item_id)
    assert canon(rows) == canon(expected_rows), (item_type, item_id)
    assert all(source_key(item_type, row) == item_id for row in rows)
    return rows


def assert_not_resolved(response: Any, *, statuses: tuple[int, ...], forbidden: Any = ()) -> None:
    assert response.status_code in statuses, (response.status_code, response.text)
    body = response.json()
    assert isinstance(body, dict), body
    assert set(body) == {'detail'}, body
    for token in forbidden:
        assert token not in response.text, (token, response.text)


def forbidden_for(facts: dict[str, Any], requested: str) -> list[str]:
    return [*SOURCE_NAMES, *(c for c in facts['charge_ids'] if c not in requested)]


def _decimals(rows: list[dict[str, Any]], column: str) -> list[Decimal]:
    return sorted(Decimal(str(row[column])) for row in rows)


def test_each_attention_item_resolves_to_its_own_source_rows(world: World) -> None:
    grouped = attention_by_type(world.client)
    expected = expected_records(world.client)
    assert len(grouped['anomaly']) == VENDOR_COUNT
    assert len(grouped['contract_review']) == 4
    assert len(grouped['contract_renewal']) == 4
    assert len(grouped['upcoming_cost']) == 2
    for item_type in ('contract_review', 'contract_renewal', 'upcoming_cost'):
        for item_id in grouped[item_type]:
            assert_resolves(
                world.client, item_type, item_id, expected.get((item_type, item_id), [])
            )
    anomaly_ids = grouped['anomaly']
    for item_id in (anomaly_ids[0], anomaly_ids[len(anomaly_ids) // 2], anomaly_ids[-1]):
        rows = assert_resolves(
            world.client, 'anomaly', item_id, expected.get(('anomaly', item_id), [])
        )
        assert len(rows) == 1


def test_component_rows_belong_only_to_the_same_canonical_identity(world: World) -> None:
    client = world.client
    d10, d20 = world.facts['d10'], world.facts['d20']

    above = get_rows(client, 'contract_review', 'review_grid/north_above_market_average')
    assert {row['contract_id'] for row in above} == {'grid/north'}
    assert {row['reason'] for row in above} == {'above_market_average'}
    assert _decimals(above, 'current_price') == [Decimal(2), Decimal(3)]

    multiple = get_rows(client, 'contract_review', 'review_grid/north_multiple_contracts_same_type')
    assert [row['contract_id'] for row in multiple] == ['grid/north']
    assert _decimals(multiple, 'current_price') == [Decimal(1)]

    grid = get_rows(client, 'contract_review', 'review_grid_multiple_contracts_same_type')
    assert [row['contract_id'] for row in grid] == ['grid']
    grid_north = get_rows(client, 'contract_review', 'review_grid_north_multiple_contracts_same_type')
    assert [row['contract_id'] for row in grid_north] == ['grid_north']

    renewal = get_rows(client, 'contract_renewal', 'renewal_grid/north_' + d10)
    assert {row['contract_id'] for row in renewal} == {'grid/north'}
    assert {row['renewal_date'] for row in renewal} == {d10}
    assert _decimals(renewal, 'current_price') == [Decimal(1), Decimal(2)]

    later = get_rows(client, 'contract_renewal', 'renewal_grid/north_' + d20)
    assert _decimals(later, 'current_price') == [Decimal(3)]
    assert [row['contract_id'] for row in get_rows(client, 'contract_renewal', 'renewal_grid_' + d10)] == ['grid']
    assert [
        row['contract_id']
        for row in get_rows(client, 'contract_renewal', 'renewal_grid_north_' + d20)
    ] == ['grid_north']


def test_equal_looking_upcoming_charges_resolve_to_distinct_rows(world: World) -> None:
    upcoming_ids = attention_by_type(world.client)['upcoming_cost']
    assert len(upcoming_ids) == 2
    resolved = []
    for item_id in upcoming_ids:
        rows = get_rows(world.client, 'upcoming_cost', item_id)
        assert len(rows) == 1
        assert source_key('upcoming_cost', rows[0]) == item_id
        resolved.append(rows[0])
    assert sorted(row['charge_id'] for row in resolved) == world.facts['charge_ids']
    visible = {
        (row['contract_name'], row['expected_date'], json.dumps(row['expected_amount']))
        for row in resolved
    }
    assert len(visible) == 1


def test_out_of_first_page_anomaly_is_selected_by_exact_key(world: World) -> None:
    rows = list_rows(world.client, 'anomaly')
    assert len(rows) == VENDOR_COUNT
    smallest = next(row for row in rows if row['counterparty_name'] == 'Vendor 000')
    for row in (smallest, rows[-1], rows[VENDOR_COUNT - 2]):
        item_id = source_key('anomaly', row)
        assert get_rows(world.client, 'anomaly', item_id) == [row]


def test_unknown_excluded_cross_type_and_malformed_keys_never_resolve(world: World) -> None:
    client, facts = world.client, world.facts
    grouped = attention_by_type(client)
    expected = expected_records(client)
    sample = {item_type: grouped[item_type][-1] for item_type in SEGMENTS}
    for item_type, item_id in sample.items():
        assert_resolves(client, item_type, item_id, expected.get((item_type, item_id), []))

    d10, d20 = facts['d10'], facts['d20']
    upcoming = list_rows(client, 'upcoming_cost')[0]
    charge, due = upcoming['charge_id'], upcoming['expected_date']
    next_day = str(date.fromisoformat(due) + timedelta(days=1))
    anomaly_tid = str(list_rows(client, 'anomaly')[0]['transaction_id'])
    regular = regular_transaction_keys(world.ts)
    assert regular

    unknown_or_excluded = [
        ('anomaly', 'anomaly_0000000000000000'),
        *(('anomaly', 'anomaly_' + key) for key in regular),
        ('contract_review', 'review_nope_multiple_contracts_same_type'),
        ('contract_review', 'review_grid_above_market_average'),
        ('contract_review', 'review_grid/north_expired_contract'),
        ('contract_renewal', 'renewal_nope_' + d10),
        ('contract_renewal', 'renewal_grid_' + d20),
        ('contract_renewal', 'renewal_grid_north_' + d10),
        ('upcoming_cost', 'upcoming_ffffffffffffffff_' + due),
        ('upcoming_cost', 'upcoming_' + charge + '_' + next_day),
    ]
    for item_type, item_id in unknown_or_excluded:
        assert (item_type, item_id) not in expected
        assert_not_resolved(
            get_record(client, item_type, item_id),
            statuses=(404,),
            forbidden=forbidden_for(facts, item_id),
        )

    for item_type, item_id in sample.items():
        for other in SEGMENTS:
            if other == item_type:
                continue
            assert_not_resolved(
                get_record(client, other, item_id),
                statuses=(400, 404),
                forbidden=forbidden_for(facts, item_id),
            )

    malformed: dict[str, list[str]] = {
        'anomaly': [
            'anomaly_',
            'anomaly',
            anomaly_tid,
            'anomaly_' + anomaly_tid + '_',
            'anomaly_' + anomaly_tid + 'x',
            'anomaly_%',
            'anomaly_' + QUOTE + ' OR ' + QUOTE + '1' + QUOTE + '=' + QUOTE + '1',
        ],
        'contract_review': [
            'review_',
            'review_grid',
            'review_grid_',
            'review_grid_%',
            'review_%_multiple_contracts_same_type',
            'review_grid/north',
            'review_grid/north_above_market_average/extra',
            'review__above_market_average',
        ],
        'contract_renewal': [
            'renewal_',
            'renewal_grid',
            'renewal_grid_',
            'renewal_grid_not-a-date',
            'renewal_grid_' + d10 + 'x',
            'renewal__' + d10,
            'renewal_%_' + d10,
            'renewal_grid/north_' + d10 + '_' + d10,
        ],
        'upcoming_cost': [
            'upcoming_',
            'upcoming_' + charge,
            'upcoming_' + charge + '_',
            'upcoming_' + charge + '_' + due + '_x',
            'upcoming__' + due,
            'upcoming_%_' + due,
            'upcoming_None_' + due,
            'upcoming_' + charge[:8] + '_' + due,
        ],
    }
    if anomaly_tid.upper() != anomaly_tid:
        malformed['anomaly'].append('anomaly_' + anomaly_tid.upper())
    for item_type, item_ids in malformed.items():
        for item_id in item_ids:
            assert (item_type, item_id) not in expected
            assert_not_resolved(
                get_record(client, item_type, item_id),
                statuses=(400, 404, 422),
                forbidden=forbidden_for(facts, item_id),
            )


def test_published_reads_never_fall_back_to_the_warehouse(tmp_path: Path) -> None:
    world = build_world(tmp_path, 'published')
    client = world.client
    vendor = next(
        row for row in list_rows(client, 'anomaly') if row['counterparty_name'] == 'Vendor 005'
    )
    vendor_id = source_key('anomaly', vendor)
    today = world.facts['today']
    world.ts.load_transactions(
        [
            {
                'booked_at': str(today - timedelta(days=1)),
                'account_id': 'bank',
                'counterparty_name': 'Vendor 005',
                'amount': '-105',
                'currency': 'EUR',
                'description': 'repeat purchase',
            },
            {
                'booked_at': str(today),
                'account_id': 'bank',
                'counterparty_name': 'Late Vendor',
                'amount': '-777',
                'currency': 'EUR',
                'description': 'late purchase',
            },
        ],
        run_id='late-transactions',
    )
    world.ts.refresh_publications(['mart_transaction_anomalies_current', 'mart_open_attention_items'])
    warehouse_reporting = ReportingService(world.ts, access_mode=ReportingAccessMode.WAREHOUSE)
    warehouse_rows = warehouse_reporting.get_transaction_anomalies_current()
    warehouse_ids = {'anomaly_' + str(row['transaction_id']) for row in warehouse_rows}
    late_ids = sorted(
        'anomaly_' + str(row['transaction_id'])
        for row in warehouse_rows
        if row['counterparty_name'] == 'Late Vendor'
    )
    assert vendor_id not in warehouse_ids
    assert len(late_ids) == 1
    late_id = late_ids[0]

    # Published authority: the published row still resolves, the warehouse-only
    # row is provably absent from the publication.
    assert get_rows(client, 'anomaly', vendor_id) == [vendor]
    assert_not_resolved(get_record(client, 'anomaly', late_id), statuses=(404,), forbidden=SOURCE_NAMES)

    warehouse_client = make_client(tmp_path, world.ts, warehouse_reporting, name='warehouse-reader')
    assert_not_resolved(
        get_record(warehouse_client, 'anomaly', vendor_id), statuses=(404,), forbidden=SOURCE_NAMES
    )
    late_rows = get_rows(warehouse_client, 'anomaly', late_id)
    assert [row['counterparty_name'] for row in late_rows] == ['Late Vendor']


def test_stale_null_published_identities_are_unavailable_not_absent(tmp_path: Path) -> None:
    world = build_world(tmp_path, 'published')
    client, store, facts = world.client, world.store, world.facts
    assert store is not None
    grouped = attention_by_type(client)
    expected = expected_records(client)
    upcoming_ids = grouped['upcoming_cost']
    assert len(upcoming_ids) == 2
    for item_id in upcoming_ids:
        assert_resolves(client, 'upcoming_cost', item_id, expected.get(('upcoming_cost', item_id), []))
    due = list_rows(client, 'upcoming_cost')[0]['expected_date']
    unknown = 'upcoming_ffffffffffffffff_' + due
    none_key = 'upcoming_None_' + due
    for item_id in (unknown, none_key):
        assert_not_resolved(
            get_record(client, 'upcoming_cost', item_id),
            statuses=(404,),
            forbidden=forbidden_for(facts, item_id),
        )

    # Stage-A shape: the CURRENT published upcoming publication is stale with
    # NULL identities while the warehouse already holds canonical charge ids.
    store.store.execute('UPDATE mart_upcoming_fixed_costs_30d SET charge_id = NULL')
    warehouse = ReportingService(
        world.ts, access_mode=ReportingAccessMode.WAREHOUSE
    ).get_upcoming_fixed_costs_30d()
    assert sorted(str(row['charge_id']) for row in warehouse) == facts['charge_ids']
    for item_id in [*upcoming_ids, unknown, none_key]:
        assert_not_resolved(
            get_record(client, 'upcoming_cost', item_id),
            statuses=(503,),
            forbidden=forbidden_for(facts, item_id),
        )
    for item_type in ('anomaly', 'contract_review', 'contract_renewal'):
        item_id = grouped[item_type][0]
        assert_resolves(client, item_type, item_id, expected.get((item_type, item_id), []))


def test_partially_null_identity_cannot_prove_absence(tmp_path: Path) -> None:
    world = build_world(tmp_path, 'published')
    client, store, facts = world.client, world.store, world.facts
    assert store is not None
    upcoming_ids = attention_by_type(client)['upcoming_cost']
    expected = expected_records(client)
    nulled_charge = facts['charge_ids'][0]
    nulled_id = next(item_id for item_id in upcoming_ids if nulled_charge in item_id)
    intact_id = next(item_id for item_id in upcoming_ids if item_id != nulled_id)
    assert_resolves(client, 'upcoming_cost', nulled_id, expected.get(('upcoming_cost', nulled_id), []))
    due = list_rows(client, 'upcoming_cost')[0]['expected_date']
    unknown = 'upcoming_ffffffffffffffff_' + due

    store.store.execute(
        'UPDATE mart_upcoming_fixed_costs_30d SET charge_id = NULL WHERE charge_id = ?',
        [nulled_charge],
    )
    for item_id in (nulled_id, unknown):
        assert_not_resolved(
            get_record(client, 'upcoming_cost', item_id),
            statuses=(503,),
            forbidden=forbidden_for(facts, item_id),
        )
    assert_resolves(client, 'upcoming_cost', intact_id, expected[('upcoming_cost', intact_id)])


def test_unpublished_source_relation_is_unavailable(tmp_path: Path) -> None:
    world = build_world(tmp_path, 'published')
    client, store, facts = world.client, world.store, world.facts
    assert store is not None
    grouped = attention_by_type(client)
    expected = expected_records(client)
    renewal_id = grouped['contract_renewal'][0]
    review_id = grouped['contract_review'][0]
    assert_resolves(client, 'contract_renewal', renewal_id, expected.get(('contract_renewal', renewal_id), []))

    store.store.execute('DROP TABLE mart_contract_renewal_watchlist')
    assert ReportingService(
        world.ts, access_mode=ReportingAccessMode.WAREHOUSE
    ).get_contract_renewal_watchlist()
    assert_not_resolved(
        get_record(client, 'contract_renewal', renewal_id),
        statuses=(503,),
        forbidden=forbidden_for(facts, renewal_id),
    )
    assert_resolves(client, 'contract_review', review_id, expected.get(('contract_review', review_id), []))


def _resolve_schema(schema: dict[str, Any], components: dict[str, Any]) -> dict[str, Any]:
    seen: set[str] = set()
    while '$ref' in schema:
        ref = schema['$ref']
        assert ref.startswith('#/components/schemas/') and ref not in seen
        seen.add(ref)
        schema = components[ref.rsplit('/', 1)[-1]]
    return schema


def test_record_routes_are_published_in_generated_contracts(tmp_path: Path) -> None:
    ts = TransformationService(DuckDBStore.memory())
    client = make_client(
        tmp_path,
        ts,
        ReportingService(ts, access_mode=ReportingAccessMode.WAREHOUSE),
        name='contracts',
    )
    live = client.app.openapi()
    generated = json.loads(
        (REPO_ROOT / 'apps/web/frontend/generated/openapi.json').read_text()
    )
    typescript = (REPO_ROOT / 'apps/web/frontend/generated/api.d.ts').read_text()
    for item_type, segment in SEGMENTS.items():
        path = '/reports/' + segment + '/records/{item_id}'
        assert path in live['paths'], path
        operation = live['paths'][path]['get']
        path_params = [
            parameter['name']
            for parameter in operation.get('parameters', [])
            if parameter.get('in') == 'path'
        ]
        assert path_params == ['item_id']
        schema = operation['responses']['200']['content']['application/json']['schema']
        components = live['components']['schemas']
        response_schema = _resolve_schema(schema, components)
        properties = response_schema['properties']
        assert set(properties) == {'item_id', 'rows'}
        assert set(response_schema['required']) == {'item_id', 'rows'}
        assert _resolve_schema(properties['item_id'], components)['type'] == 'string'
        rows_schema = _resolve_schema(properties['rows'], components)
        assert rows_schema['type'] == 'array'
        assert _resolve_schema(rows_schema['items'], components) == components[ROW_MODELS[item_type]]
        assert path in generated['paths'], path
        assert generated['paths'][path] == live['paths'][path]
        assert path in typescript, path


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


@pytest.mark.integration
@pytest.mark.slow
def test_published_postgres_attention_records(tmp_path: Path) -> None:
    ts = TransformationService(DuckDBStore.memory())
    facts = seed(ts)
    refresh(ts)
    with running_postgres_container() as dsn:
        store = PostgresReportingStore(dsn)
        publish(ts, store)
        reporting = ReportingService(
            ts,
            publication_store=store,
            access_mode=ReportingAccessMode.PUBLISHED,
        )
        client = make_client(tmp_path, ts, reporting, name='postgres')
        grouped = attention_by_type(client)
        expected = expected_records(client)
        assert any('/' in item_id for item_id in grouped['contract_review'])
        assert any('/' in item_id for item_id in grouped['contract_renewal'])
        for item_type in ('contract_review', 'contract_renewal', 'upcoming_cost'):
            for item_id in grouped[item_type]:
                assert_resolves(client, item_type, item_id, expected.get((item_type, item_id), []))
        for item_id in (grouped['anomaly'][0], grouped['anomaly'][-1]):
            assert_resolves(client, 'anomaly', item_id, expected.get(('anomaly', item_id), []))

        due = list_rows(client, 'upcoming_cost')[0]['expected_date']
        unknown = 'upcoming_ffffffffffffffff_' + due
        none_key = 'upcoming_None_' + due
        for item_id in (unknown, none_key):
            assert_not_resolved(
                get_record(client, 'upcoming_cost', item_id),
                statuses=(404,),
                forbidden=forbidden_for(facts, item_id),
            )
        assert_not_resolved(
            get_record(client, 'contract_review', 'review_grid_above_market_average'),
            statuses=(404,),
            forbidden=SOURCE_NAMES,
        )

        store.execute_statements([('UPDATE mart_upcoming_fixed_costs_30d SET charge_id = NULL', [])])
        for item_id in [*grouped['upcoming_cost'], unknown, none_key]:
            assert_not_resolved(
                get_record(client, 'upcoming_cost', item_id),
                statuses=(503,),
                forbidden=forbidden_for(facts, item_id),
            )

        store.execute_statements([('DROP TABLE mart_contract_renewal_watchlist', [])])
        renewal_id = grouped['contract_renewal'][0]
        assert_not_resolved(
            get_record(client, 'contract_renewal', renewal_id),
            statuses=(503,),
            forbidden=forbidden_for(facts, renewal_id),
        )
        review_id = grouped['contract_review'][0]
        assert_resolves(client, 'contract_review', review_id, expected.get(('contract_review', review_id), []))


def _observe_source_queries(world: World, monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    # Replay each real read on a separate DuckDB cursor before delegating it to
    # the production store. The replay uses the actual SQL, bindings and data;
    # it neither changes nor supplies the result consumed by the application.
    target = world.ts.store if world.mode == 'warehouse' else world.store
    assert target is not None
    database = world.ts.store if world.mode == 'warehouse' else world.store.store
    calls: list[Any] = []

    def wrap(method: Any) -> Any:
        def recording(sql: Any, params: Any = None) -> Any:
            statement = sql if isinstance(sql, str) else sql.as_string(None)
            lowered = statement.lower()
            if any(relation in lowered for relation in SOURCE_RELATIONS):
                translated = statement if world.mode == 'warehouse' else DuckPublicationStore._sql(sql)
                cursor = database.connection.cursor()
                try:
                    result = cursor.execute(translated, list(params or []))
                    columns = [column[0] for column in result.description]
                    rows = [dict(zip(columns, row)) for row in result.fetchall()]
                finally:
                    cursor.close()
                calls.append((lowered, list(params or []), columns, rows))
            return method(sql, params)
        return recording

    methods = ('fetchall', 'fetchall_dicts', 'execute') if world.mode == 'warehouse' else ('fetchall_dicts',)
    for name in methods:
        monkeypatch.setattr(target, name, wrap(getattr(target, name)))
    return calls


def _assert_observed_selection(
    calls: list[Any], relation: str, item_type: str, item_id: str, *, positive: bool
) -> None:
    source = [call for call in calls if relation in call[0]]
    assert source, calls
    identity_columns = {
        'anomaly': {'transaction_id'},
        'contract_review': {'contract_id', 'reason'},
        'contract_renewal': {'contract_id', 'renewal_date'},
        'upcoming_cost': {'charge_id', 'expected_date'},
    }[item_type]
    selected = []
    for sql, params, columns, rows in source:
        if identity_columns <= set(columns):
            # This is observed before application code receives any rows. A
            # tautology or fetch-all cannot hide behind later Python filtering.
            assert item_id in params, (sql, params)
            assert item_id not in sql
            assert 'where' in sql and ('?' in sql or '%s' in sql), sql
            assert 'limit' not in sql[:sql.index('where')], sql
            assert all(source_key(item_type, row) == item_id for row in rows), (sql, rows)
            selected.extend(rows)
        else:
            # Only a scalar metadata/existence query may omit identity columns;
            # it must not fetch an unfiltered column of source data.
            assert len(columns) == 1 and len(rows) <= 1, (sql, columns, rows)
            assert ('count(' in sql or 'exists' in sql or 'select 1' in sql), sql
            assert 'is null' in sql, sql
    assert any(item_id in params for _, params, _, _ in source), source
    if positive:
        assert selected, source


@pytest.mark.parametrize('item_type', list(SEGMENTS))
def test_lookup_binds_complete_key_at_source_before_limit(
    world: World, item_type: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = expected_records(world.client)
    ids = attention_by_type(world.client)[item_type]
    item_id = next((key for key in ids if '/' in key), ids[-1])
    relation = dict(zip(SEGMENTS, SOURCE_RELATIONS))[item_type]
    # Confirm there are competing source identities in the observed relation.
    assert len({key for kind, key in expected if kind == item_type}) > 1
    calls = _observe_source_queries(world, monkeypatch)
    assert_resolves(world.client, item_type, item_id, expected[(item_type, item_id)])
    _assert_observed_selection(calls, relation, item_type, item_id, positive=True)


def test_stale_identity_probe_does_not_fetch_source_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = build_world(tmp_path, 'published')
    assert world.store is not None
    ids = attention_by_type(world.client)['upcoming_cost']
    expected = expected_records(world.client)
    assert_resolves(world.client, 'upcoming_cost', ids[0], expected[('upcoming_cost', ids[0])])
    world.store.store.execute('UPDATE mart_upcoming_fixed_costs_30d SET charge_id = NULL')
    calls = _observe_source_queries(world, monkeypatch)
    unknown = 'upcoming_ffffffffffffffff_2099-12-31'
    assert_not_resolved(get_record(world.client, 'upcoming_cost', unknown), statuses=(503,))
    relation = 'mart_upcoming_fixed_costs_30d'
    _assert_observed_selection(calls, relation, 'upcoming_cost', unknown, positive=False)
    probes = [(sql, columns, rows) for sql, _, columns, rows in calls
              if relation in sql and 'is null' in sql]
    assert probes, calls
    for sql, columns, rows in probes:
        assert len(columns) == 1 and len(rows) <= 1, (sql, columns, rows)
        assert 'count(' in sql or 'exists' in sql or 'select 1' in sql, sql


def test_unknown_and_unavailable_details_do_not_disclose_stored_fields(tmp_path: Path) -> None:
    world = build_world(tmp_path, 'published')
    assert world.store is not None
    expected = expected_records(world.client)
    ids = attention_by_type(world.client)
    assert_resolves(world.client, 'contract_review', ids['contract_review'][0],
                    expected[('contract_review', ids['contract_review'][0])])
    # These values are stored facts, none supplied in either request. Check
    # whole meaningful field values, rather than banning numeric substrings.
    secrets = [*SOURCE_NAMES, 'grid/north', 'grid_north', 'grid',
               'above_market_average', 'multiple_contracts_same_type',
               world.facts['d10'], world.facts['d20'], *world.facts['charge_ids'], '12.50']
    unknown = 'review_unrelated_nonexistent'
    assert_not_resolved(get_record(world.client, 'contract_review', unknown),
                        statuses=(404,), forbidden=secrets)
    world.store.store.execute('UPDATE mart_upcoming_fixed_costs_30d SET charge_id = NULL')
    assert_not_resolved(get_record(world.client, 'upcoming_cost', 'upcoming_unknown_2099-12-31'),
                        statuses=(503,), forbidden=secrets)
