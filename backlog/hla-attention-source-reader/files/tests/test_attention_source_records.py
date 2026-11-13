from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any

import duckdb
import psycopg
import pytest
from pydantic import ValidationError

from apps.api.routes.report_routes import (
    CONTRACT_RENEWAL_WATCHLIST_ROW_MODEL,
    CONTRACT_REVIEW_CANDIDATES_ROW_MODEL,
    TRANSACTION_ANOMALIES_ROW_MODEL,
    UPCOMING_FIXED_COSTS_ROW_MODEL,
)
from apps.api.support import to_jsonable
from packages.domains.finance.pipelines.subscription_models import subscription_charge_id
from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
from packages.pipelines.transformation_service import TransformationService
from packages.storage.duckdb_store import DuckDBStore, WarehouseBusyError
from packages.storage.postgres_reporting import PostgresReportingStore
from tests.postgres_test_support import docker_is_available, running_postgres_container

VENDOR_COUNT = 240
SOURCE = {
    'anomaly': ('mart_transaction_anomalies_current', ('transaction_id',)),
    'contract_review': ('mart_contract_review_candidates', ('contract_id', 'reason')),
    'contract_renewal': ('mart_contract_renewal_watchlist', ('contract_id', 'renewal_date')),
    'upcoming_cost': ('mart_upcoming_fixed_costs_30d', ('charge_id', 'expected_date')),
}
REFRESH = ['mart_subscription_summary', 'mart_upcoming_fixed_costs_30d',
           'mart_contract_price_current', 'mart_contract_review_candidates',
           'mart_contract_renewal_watchlist', 'mart_transaction_anomalies_current',
           'mart_open_attention_items']
MODELS = {'anomaly': TRANSACTION_ANOMALIES_ROW_MODEL,
          'contract_review': CONTRACT_REVIEW_CANDIDATES_ROW_MODEL,
          'contract_renewal': CONTRACT_RENEWAL_WATCHLIST_ROW_MODEL,
          'upcoming_cost': UPCOMING_FIXED_COSTS_ROW_MODEL}


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
            _price('None/utility', 'energy', '1', d10, today),
            _price('None/utility', 'transfer', '2', d10, today),
            _price('None/utility', 'tax', '3', d20, today),
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



def key(kind: str, row: dict[str, Any]) -> str:
    if kind == 'anomaly':
        return 'anomaly_' + str(row['transaction_id'])
    if kind == 'contract_review':
        return 'review_' + str(row['contract_id']) + '_' + str(row['reason'])
    if kind == 'contract_renewal':
        return 'renewal_' + str(row['contract_id']) + '_' + str(row['renewal_date'])
    return 'upcoming_' + str(row['charge_id']) + '_' + str(row['expected_date'])


def unknown_key(kind: str, row: dict[str, Any]) -> str:
    value = dict(row)
    field = {'anomaly': 'transaction_id', 'contract_review': 'contract_id',
             'contract_renewal': 'contract_id', 'upcoming_cost': 'charge_id'}[kind]
    value[field] = 'ffffffffffffffff'
    return key(kind, value)


def canonical(rows: list[dict[str, Any]]) -> list[str]:
    return sorted(json.dumps(to_jsonable(row), sort_keys=True) for row in rows)


def grouped(rows: list[dict[str, Any]], kind: str) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        result.setdefault(key(kind, row), []).append(row)
    return result


def read_all(store: Any, kind: str) -> list[dict[str, Any]]:
    return store.fetchall_dicts('SELECT * FROM ' + SOURCE[kind][0])


def facade(service: ReportingService) -> Any:
    assert callable(getattr(service, 'get_attention_record', None)), 'missing attention source reader'
    return service.get_attention_record


def errors() -> tuple[type[Exception], type[Exception]]:
    from packages.domains.overview.pipelines.attention_records import (
        AttentionRecordNotFoundError,
        AttentionRecordUnavailableError,
    )
    return AttentionRecordNotFoundError, AttentionRecordUnavailableError


@pytest.fixture
def warehouse() -> Any:
    ts = TransformationService(DuckDBStore.memory())
    facts = seed(ts)
    ts.refresh_publications(REFRESH)
    charge_rows = ts.store.fetchall_dicts('SELECT charge_id FROM mart_upcoming_fixed_costs_30d')
    assert sorted(str(row['charge_id']) for row in charge_rows) == facts['charge_ids']
    try:
        yield ts
    finally:
        ts.store.close()


def publication(ts: Any, pg: Any) -> None:
    tables = [v[0] for v in SOURCE.values()] + ['mart_open_attention_items']
    assert ReportingService(ts, publication_store=pg).publish_publications(tables) == tables


def select_groups(store: Any) -> dict[str, tuple[str, list[dict[str, Any]]]]:
    groups = {kind: grouped(read_all(store, kind), kind) for kind in SOURCE}
    # These controls are generated by the normalized loaders and production marts.
    assert len(groups['anomaly']) > 200
    assert len(groups['upcoming_cost']) >= 2
    selected = {}
    for kind, values in groups.items():
        if kind in ('contract_review', 'contract_renewal'):
            selected[kind] = next((k, v) for k, v in sorted(values.items())
                                  if 'None/utility' in k and len(v) >= 2)
        elif kind == 'anomaly':
            # Explicitly select after the first page in deterministic source order.
            ordered = sorted(values)
            assert len(ordered) > 200
            first_page = store.fetchall_dicts('SELECT transaction_id FROM ' + SOURCE[kind][0] +
                                              ' ORDER BY transaction_id LIMIT 200')
            assert ordered[200].removeprefix('anomaly_') not in {row['transaction_id'] for row in first_page}
            selected[kind] = ordered[200], values[ordered[200]]
        else:
            selected[kind] = sorted(values.items())[0]
    return selected


def observe(monkeypatch: pytest.MonkeyPatch, target: Any, *, postgres: bool) -> list[Any]:
    """Capture every query against a source before application selection, including empty results."""
    calls: list[Any] = []
    methods = ('fetchall_dicts',) if postgres else ('fetchall', 'fetchall_dicts', 'execute')
    for method in methods:
        original = getattr(target, method)

        def wrapper(sql: Any, params: Any = None, *, _original: Any = original) -> Any:
            text = sql if isinstance(sql, str) else sql.as_string(None)
            lowered = text.lower()
            if any(table in lowered for table, _ in SOURCE.values()):
                assert re.match(r'^\s*(select|with)\b', lowered), text
                if postgres:
                    result = _original(sql, params)
                    if result:
                        columns = list(result[0])
                    else:
                        # A separate cursor provides actual result metadata even for zero rows.
                        with target._connect() as conn:
                            cursor = conn.execute(sql, params or ())
                            columns = [col.name for col in cursor.description]
                    calls.append((lowered, list(params or []), columns, result))
                    return result
                cursor = target.connection.cursor()
                try:
                    query = cursor.execute(text, list(params or []))
                    columns = [col[0] for col in query.description]
                    rows = [dict(zip(columns, row)) for row in query.fetchall()]
                finally:
                    cursor.close()
                calls.append((lowered, list(params or []), columns, rows))
            return _original(sql, params)

        monkeypatch.setattr(target, method, wrapper)
    return calls


def assert_selected(calls: list[Any], kind: str, item_id: str, *, positive: bool) -> None:
    table, identities = SOURCE[kind]
    source = [call for call in calls if table in call[0]]
    assert source, calls
    observed = []
    for sql, params, columns, rows in source:
        if set(identities) <= set(columns):
            assert item_id in params and item_id not in sql, (sql, params)
            assert 'where' in sql and ('?' in sql or '%s' in sql), sql
            assert all(key(kind, row) == item_id for row in rows), (sql, rows)
            observed.extend(rows)
        else:
            # Only a provable scalar metadata/existence probe may omit identity columns.
            assert len(columns) == 1 and len(rows) <= 1, (sql, columns, rows)
            assert re.match(r'^\s*select\s+(?:count\s*\(\s*\*\s*\)|exists\s*\(|1(?:\s+as\s+\w+)?\s+from\b)', sql), sql
    assert any(item_id in params for _, params, _, _ in source), source
    if positive:
        assert observed, source


def forbid_warehouse(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    for name in ('fetchall', 'fetchall_dicts', 'execute'):
        original = getattr(DuckDBStore, name)

        def wrapper(store: Any, *args: Any, _name: str = name,
                    _original: Any = original, **kwargs: Any) -> Any:
            calls.append(_name)
            return _original(store, *args, **kwargs)

        monkeypatch.setattr(DuckDBStore, name, wrapper)
    return calls


def test_generated_fixture_and_source_sql(warehouse: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    groups = select_groups(warehouse.store)
    service = ReportingService(warehouse, access_mode=ReportingAccessMode.WAREHOUSE)
    before = canonical(service.get_open_attention_items())
    assert before == canonical(warehouse.store.fetchall_dicts('SELECT * FROM mart_open_attention_items'))
    snapshot = {kind: canonical(read_all(warehouse.store, kind)) for kind in SOURCE}
    get = facade(service)
    not_found, _ = errors()
    for kind, (item_id, want) in groups.items():
        with monkeypatch.context() as patch:
            calls = observe(patch, warehouse.store, postgres=False)
            assert canonical(get(kind, item_id)) == canonical(want)
            assert_selected(calls, kind, item_id, positive=True)
            calls.clear()
            unknown = unknown_key(kind, want[0])
            with pytest.raises(not_found):
                get(kind, unknown)
            assert_selected(calls, kind, unknown, positive=False)
    assert canonical(service.get_open_attention_items()) == before
    assert {kind: canonical(read_all(warehouse.store, kind)) for kind in SOURCE} == snapshot


def test_sql_observer_rejects_projection_and_tautology(warehouse: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    item_id, _ = select_groups(warehouse.store)['anomaly']
    with monkeypatch.context() as patch:
        calls = observe(patch, warehouse.store, postgres=False)
        warehouse.store.fetchall_dicts('SELECT counterparty_name FROM mart_transaction_anomalies_current')
        with pytest.raises(AssertionError):
            assert_selected(calls, 'anomaly', item_id, positive=True)
        calls.clear()
        warehouse.store.fetchall_dicts('SELECT * FROM mart_transaction_anomalies_current WHERE ? = ?',
                                       [item_id, item_id])
        with pytest.raises(AssertionError):
            assert_selected(calls, 'anomaly', item_id, positive=True)


def test_published_no_store_and_prefer_fallback(warehouse: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    selected = select_groups(warehouse.store)
    strict = facade(ReportingService(warehouse, access_mode=ReportingAccessMode.PUBLISHED))
    _, unavailable = errors()
    with monkeypatch.context() as patch:
        calls = forbid_warehouse(patch)
        for kind, (item_id, _) in selected.items():
            with pytest.raises(unavailable):
                strict(kind, item_id)
        assert calls == []
    prefer = facade(ReportingService(warehouse, access_mode=ReportingAccessMode.PREFER_PUBLISHED))
    for kind, (item_id, want) in selected.items():
        assert canonical(prefer(kind, item_id)) == canonical(want)


def test_warehouse_busy_and_programming_errors_propagate(warehouse: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    item_id, _ = select_groups(warehouse.store)['anomaly']
    get = facade(ReportingService(warehouse, access_mode=ReportingAccessMode.WAREHOUSE))
    for exc in (WarehouseBusyError('synthetic', 1, RuntimeError('locked')), RuntimeError('program defect')):
        with monkeypatch.context() as patch:
            def fail(*args: Any, **kwargs: Any) -> Any:
                raise exc
            for name in ('fetchall', 'fetchall_dicts', 'execute'):
                patch.setattr(warehouse.store, name, fail)
            with pytest.raises(type(exc)) as caught:
                get('anomaly', item_id)
            assert caught.value is exc


def test_warehouse_driver_failure_is_unavailable(warehouse: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    item_id, _ = select_groups(warehouse.store)['anomaly']
    get = facade(ReportingService(warehouse, access_mode=ReportingAccessMode.WAREHOUSE))
    _, unavailable = errors()
    def fail(*args: Any, **kwargs: Any) -> Any:
        raise duckdb.IOException('synthetic warehouse driver failure')
    for name in ('fetchall', 'fetchall_dicts', 'execute'):
        monkeypatch.setattr(warehouse.store, name, fail)
    with pytest.raises(unavailable):
        get('anomaly', item_id)


def required_postgres() -> Any:
    # The required slow selector must fail, not silently skip, when Docker is absent.
    assert docker_is_available(), 'mandatory Postgres qualification requires Docker'
    return running_postgres_container()


@pytest.mark.integration
@pytest.mark.slow
def test_postgres_fixture_admission_and_cleanup(warehouse: Any) -> None:
    with required_postgres() as dsn:
        pg = PostgresReportingStore(dsn)
        publication(warehouse, pg)
        groups = select_groups(pg)
        for kind, (_, expected) in groups.items():
            assert expected
            MODELS[kind].model_validate(to_jsonable(expected[0]))
        upcoming = groups['upcoming_cost'][1][0]
        with pytest.raises(ValidationError):
            UPCOMING_FIXED_COSTS_ROW_MODEL.model_validate(to_jsonable(dict(upcoming, expected_date=None)))
        columns = pg.fetchall_dicts(
            "SELECT is_nullable FROM information_schema.columns WHERE table_schema = current_schema() "
            "AND table_name = %s AND column_name = %s", ['mart_upcoming_fixed_costs_30d', 'expected_date'])
        assert columns == [{'is_nullable': 'NO'}]
        # Prove model and actual fresh publication store admit explicit empty text.
        for kind, (table, identities) in SOURCE.items():
            for column in identities:
                if column in ('expected_date', 'renewal_date'):
                    continue
                original = groups[kind][1][0]
                mutated = dict(original, **{column: ''})
                MODELS[kind].model_validate(to_jsonable(mutated))
                names = list(mutated)
                pg.execute_statements([(f"INSERT INTO {table} ({', '.join(names)}) VALUES "
                                        f"({', '.join('%s' for _ in names)})",
                                        [mutated[name] for name in names])])
                assert pg.fetchall_dicts(f'SELECT * FROM {table} WHERE {column} = %s', [''])
                pg.execute_statements([(f'DELETE FROM {table} WHERE {column} = %s', [''])])


@pytest.mark.integration
@pytest.mark.slow
def test_postgres_authority_sql_identity_and_unchanged_attention(
    warehouse: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    warehouse_groups = select_groups(warehouse.store)
    with required_postgres() as dsn:
        pg = PostgresReportingStore(dsn)
        publication(warehouse, pg)
        # Preserve generated identities while making all four publications distinguishable.
        fields = {'anomaly': 'counterparty_name', 'contract_review': 'provider',
                  'contract_renewal': 'contract_name', 'upcoming_cost': 'provider'}
        for kind, field in fields.items():
            pg.execute_statements([(f'UPDATE {SOURCE[kind][0]} SET {field} = %s', ['published-only'])])
        selected = select_groups(pg)
        # Empty display text is not an invalid identity.
        upcoming_row = selected['upcoming_cost'][1][0]
        pg.execute_statements([('UPDATE mart_upcoming_fixed_costs_30d SET provider = %s WHERE charge_id = %s',
                                ['', upcoming_row['charge_id']])])
        selected = select_groups(pg)
        for kind, (item_id, expected) in selected.items():
            assert canonical(expected) != canonical(warehouse_groups[kind][1])
            assert item_id == warehouse_groups[kind][0]
        service = ReportingService(warehouse, publication_store=pg, access_mode=ReportingAccessMode.PUBLISHED)
        prefer = ReportingService(warehouse, publication_store=pg, access_mode=ReportingAccessMode.PREFER_PUBLISHED)
        before = canonical(service.get_open_attention_items())
        assert before == canonical(pg.fetchall_dicts('SELECT * FROM mart_open_attention_items'))
        snapshot = {kind: canonical(read_all(pg, kind)) for kind in SOURCE}
        get = facade(service)
        prefer_get = facade(prefer)
        not_found, unavailable = errors()
        for kind, (item_id, expected) in selected.items():
            with monkeypatch.context() as patch:
                calls = observe(patch, pg, postgres=True)
                warehouse_calls = forbid_warehouse(patch)
                assert canonical(get(kind, item_id)) == canonical(expected)
                assert_selected(calls, kind, item_id, positive=True)
                calls.clear()
                assert canonical(prefer_get(kind, item_id)) == canonical(expected)
                assert_selected(calls, kind, item_id, positive=True)
                calls.clear()
                unknown = unknown_key(kind, expected[0])
                with pytest.raises(not_found):
                    get(kind, unknown)
                assert_selected(calls, kind, unknown, positive=False)
                assert warehouse_calls == []
        assert canonical(service.get_open_attention_items()) == before
        assert {kind: canonical(read_all(pg, kind)) for kind in SOURCE} == snapshot

        for kind, (table, identities) in SOURCE.items():
            item_id, intact = selected[kind]
            all_groups = grouped(read_all(pg, kind), kind)
            other_key, other_rows = next((k, v) for k, v in all_groups.items() if k != item_id)
            original = other_rows[0]
            for column in identities:
                if column in ('expected_date', 'renewal_date'):
                    continue
                mutated = dict(original, **{column: ''})
                MODELS[kind].model_validate(to_jsonable(mutated))
                forged = key(kind, mutated)
                unknown = unknown_key(kind, intact[0])
                with pytest.raises(not_found):
                    get(kind, unknown)
                where = ' AND '.join(f'{name} = %s' for name in identities)
                pg.execute_statements([(f'UPDATE {table} SET {column} = %s WHERE {where}',
                                        ['', *(original[name] for name in identities)])])
                with monkeypatch.context() as patch:
                    calls = forbid_warehouse(patch)
                    for missing in (unknown, forged, other_key):
                        with pytest.raises(unavailable):
                            get(kind, missing)
                    assert canonical(get(kind, item_id)) == canonical(intact)
                    assert calls == []
                publication(warehouse, pg)
                # Re-establish the published-only values for all kinds after republishing.
                for changed_kind, field in fields.items():
                    pg.execute_statements([(f'UPDATE {SOURCE[changed_kind][0]} SET {field} = %s', ['published-only'])])
                pg.execute_statements([('UPDATE mart_upcoming_fixed_costs_30d SET provider = %s WHERE charge_id = %s',
                                        ['', upcoming_row['charge_id']])])

        item_id, intact = selected['upcoming_cost']
        charges = grouped(read_all(pg, 'upcoming_cost'), 'upcoming_cost')
        other_key, other_rows = next((k, v) for k, v in charges.items() if k != item_id)
        unknown = unknown_key('upcoming_cost', intact[0])
        with pytest.raises(not_found):
            get('upcoming_cost', unknown)
        pg.execute_statements([('UPDATE mart_upcoming_fixed_costs_30d SET charge_id = NULL WHERE charge_id = %s',
                                [other_rows[0]['charge_id']])])
        with monkeypatch.context() as patch:
            calls = forbid_warehouse(patch)
            for missing in (other_key, unknown):
                with pytest.raises(unavailable):
                    get('upcoming_cost', missing)
            assert canonical(get('upcoming_cost', item_id)) == canonical(intact)
            assert calls == []
        pg.execute_statements([('ALTER TABLE mart_upcoming_fixed_costs_30d DROP COLUMN charge_id', [])])
        with monkeypatch.context() as patch:
            calls = forbid_warehouse(patch)
            for missing in (item_id, unknown):
                with pytest.raises(unavailable):
                    get('upcoming_cost', missing)
            other_kind = 'contract_review'
            assert canonical(get(other_kind, selected[other_kind][0])) == canonical(selected[other_kind][1])
            assert calls == []
        pg.execute_statements([('DROP TABLE mart_transaction_anomalies_current', [])])
        with monkeypatch.context() as patch:
            calls = forbid_warehouse(patch)
            for missing in (selected['anomaly'][0], unknown_key('anomaly', selected['anomaly'][1][0])):
                with pytest.raises(unavailable):
                    get('anomaly', missing)
            assert calls == []


@pytest.mark.integration
@pytest.mark.slow
def test_postgres_connection_failure_is_sanitized_without_fallback(
    warehouse: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    item_id, _ = select_groups(warehouse.store)['anomaly']
    with required_postgres() as dsn:
        pg = PostgresReportingStore(dsn)
        publication(warehouse, pg)
        get = facade(ReportingService(warehouse, publication_store=pg, access_mode=ReportingAccessMode.PUBLISHED))
        _, unavailable = errors()
        marker = 'synthetic-private-driver-marker'
        def fail(**kwargs: Any) -> Any:
            raise psycopg.OperationalError(marker)
        with monkeypatch.context() as patch:
            calls = forbid_warehouse(patch)
            patch.setattr(pg, '_connect', fail)
            with pytest.raises(unavailable) as caught:
                get('anomaly', item_id)
            assert marker not in str(caught.value)
            assert calls == []
        error = RuntimeError('programming defect')
        def fail_program(**kwargs: Any) -> Any:
            raise error
        monkeypatch.setattr(pg, '_connect', fail_program)
        with pytest.raises(RuntimeError) as caught:
            get('anomaly', item_id)
        assert caught.value is error


@pytest.mark.parametrize('failure_kind', ['driver', 'busy', 'program'])
def test_warehouse_real_lease_acquisition_failures(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch, failure_kind: str
) -> None:
    import packages.storage.duckdb_store as duckdb_store
    from packages.pipelines.warehouse_session import (
        WarehouseSessionManager,
        WarehouseSessionTransformationService,
        _ReadOnlyTransformationService,
    )

    path = tmp_path / 'synthetic.duckdb'
    store = DuckDBStore.open(str(path))
    try:
        ts = TransformationService(store)
        seed(ts)
        ts.refresh_publications(REFRESH)
        item_id, expected = select_groups(store)['anomaly']
    finally:
        store.close()

    def build(leased_store: Any, read_only: bool) -> Any:
        if read_only:
            return _ReadOnlyTransformationService(leased_store)
        return TransformationService(leased_store)

    manager = WarehouseSessionManager(path, build, idle_timeout_seconds=0)
    service = ReportingService(
        WarehouseSessionTransformationService(manager), access_mode=ReportingAccessMode.WAREHOUSE
    )
    try:
        get = facade(service)
        _, unavailable = errors()
        assert canonical(get('anomaly', item_id)) == canonical(expected)
        assert manager.mode is None
        marker = 'synthetic-private-acquisition-marker'
        failures = {
            'driver': duckdb.IOException(marker),
            'busy': WarehouseBusyError('synthetic', 1, RuntimeError('held')),
            'program': RuntimeError(marker),
        }
        failure = failures[failure_kind]
        calls = []

        def fail(*args: Any, **kwargs: Any) -> Any:
            calls.append((args, kwargs))
            raise failure

        caught = None
        with monkeypatch.context() as patch:
            patch.setattr(duckdb_store, 'connect_with_lock_retry', fail)
            try:
                get('anomaly', item_id)
            except Exception as exc:
                caught = exc
        assert len(calls) == 1
        assert manager.mode is None
        assert canonical(get('anomaly', item_id)) == canonical(expected)
        assert manager.mode is None
        if failure_kind == 'driver':
            assert isinstance(caught, unavailable)
            assert marker not in str(caught)
        else:
            assert caught is failure
    finally:
        manager.stop()
