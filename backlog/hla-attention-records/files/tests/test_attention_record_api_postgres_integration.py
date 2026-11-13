# Attention item records over the real disposable Postgres publication store.
#
# Mode exercised: ReportingAccessMode.PUBLISHED with PostgresReportingStore in a
# disposable postgres:16-alpine container (tests.postgres_test_support).
# Marked integration and slow, so the default pytest addopts exclude it; run
# it explicitly before landing:
#   pytest -m slow tests/test_attention_record_api_postgres_integration.py
# The shared container helper skips when Docker is unavailable. A skip is
# not a pass.
from __future__ import annotations

from pathlib import Path

import pytest

from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
from packages.pipelines.transformation_service import TransformationService
from packages.storage.duckdb_store import DuckDBStore
from packages.storage.postgres_reporting import PostgresReportingStore
from tests.postgres_test_support import running_postgres_container
from tests.test_attention_record_api import (
    SOURCE_NAMES,
    assert_not_resolved,
    assert_resolves,
    attention_by_type,
    expected_records,
    forbidden_for,
    get_record,
    list_rows,
    make_client,
    publish,
    refresh,
    seed,
)

pytestmark = [pytest.mark.integration, pytest.mark.slow]


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
