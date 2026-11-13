"""Synthetic stage A legacy-upgrade promotion/capture probe. No live services."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from packages.domains.finance.pipelines.subscription_models import (
    MART_SUBSCRIPTION_SUMMARY_COLUMNS, MART_UPCOMING_FIXED_COSTS_30D_COLUMNS,
)
from packages.pipelines.household_packages import BUILTIN_TRANSFORMATION_PACKAGE_SPECS_BY_HANDLER_KEY
from packages.pipelines.promotion_types import PromotionResult
from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService, publish_promotion_reporting
from packages.pipelines.reporting_snapshots import PublicationSnapshot, PublicationSnapshotStore
from packages.pipelines.transformation_service import TransformationService
from packages.storage.duckdb_store import DuckDBStore
from packages.storage.migration_runner import apply_pending_duckdb_migrations
from packages.storage.postgres_reporting import PostgresReportingStore
from tests.postgres_test_support import running_postgres_container
from tests.test_attention_identity import MIGRATIONS, _seed

KEY = 'mart_subscription_summary'
UPCOMING = 'mart_upcoming_fixed_costs_30d'

def run(dsn: str | None) -> dict:
    with tempfile.TemporaryDirectory(prefix='hla-stage-a-migrations-') as directory:
        old = Path(directory)
        for migration in sorted(MIGRATIONS.glob('*.sql')):
            if migration.name < '0019':
                (old / migration.name).write_text(migration.read_text())
        warehouse = DuckDBStore.memory()
        apply_pending_duckdb_migrations(warehouse.connection, old)
        ts = TransformationService(warehouse)
        charge_ids, _ = _seed(ts)
        warehouse.execute('''INSERT INTO mart_subscription_summary
            SELECT contract_id, contract_name, provider, billing_cycle, amount, currency,
                   start_date, end_date, amount, 'active' FROM fact_subscription_charge''')
        warehouse.execute('''INSERT INTO mart_upcoming_fixed_costs_30d
            SELECT contract_name, provider, billing_cycle, amount, currency, CURRENT_DATE, 'high'
            FROM fact_subscription_charge''')
        apply_pending_duckdb_migrations(warehouse.connection, MIGRATIONS)
        old_summary = warehouse.fetchall_dicts('SELECT * FROM mart_subscription_summary')
        old_upcoming = warehouse.fetchall_dicts('SELECT * FROM mart_upcoming_fixed_costs_30d')
        pub = PostgresReportingStore(dsn, schema='probe') if dsn else None
        if pub:
            for table, columns, rows in ((KEY, MART_SUBSCRIPTION_SUMMARY_COLUMNS, old_summary),
                                          (UPCOMING, MART_UPCOMING_FIXED_COSTS_30D_COLUMNS, old_upcoming)):
                pub.replace_rows(table, columns, rows)
        today = warehouse.fetchall('SELECT CURRENT_DATE')[0][0]
        active = today.strftime('%Y-%m')
        earlier = (today.replace(day=1).toordinal() - 1)
        from datetime import date
        prior = date.fromordinal(earlier).strftime('%Y-%m')
        previous = PublicationSnapshot(KEY, prior, '2020-01-01T00:00:00+00:00', 'old-prior', [{'contract_name':'old-prior'}])
        current = PublicationSnapshot(KEY, active, '2020-02-01T00:00:00+00:00', 'old-active', [{'contract_name':'old-active'}])
        snapshot_stores = [PublicationSnapshotStore.for_duckdb(warehouse)]
        if pub:
            snapshot_stores.append(PublicationSnapshotStore.for_postgres(pub))
        for snapshots in snapshot_stores:
            snapshots.write(previous, retention_months=24)
            snapshots.write(current, retention_months=24)
        def raw(store):
            placeholder = '%s' if store is pub else '?'
            return store.fetchall_dicts(
                f'SELECT reference_month, captured_at, run_id, rows_json FROM reporting_publication_snapshot '
                f'WHERE publication_key = {placeholder} ORDER BY reference_month', [KEY])
        prior_before = [raw(store)[0] for store in ([warehouse, pub] if pub else [warehouse])]
        package = BUILTIN_TRANSFORMATION_PACKAGE_SPECS_BY_HANDLER_KEY['account_transactions']
        refreshed = ts.refresh_publications(package.refresh_publication_keys)
        assert refreshed[:2] == [KEY, UPCOMING]
        rs = ReportingService(ts, publication_store=pub,
            access_mode=ReportingAccessMode.PUBLISHED if pub else ReportingAccessMode.WAREHOUSE)
        published_before = (rs.get_subscription_summary(), rs.get_upcoming_fixed_costs_30d()) if pub else None
        result = PromotionResult(run_id='new-finance-run' , facts_loaded=1,
                                 marts_refreshed=refreshed, publication_keys=list(package.publication_keys))
        published = publish_promotion_reporting(rs, result)
        outcomes = []
        for index, store in enumerate([warehouse, pub] if pub else [warehouse]):
            rows = raw(store)
            assert len(rows) == 2
            assert rows[0] == prior_before[index]
            assert rows[1]['reference_month'] == active
            assert rows[1]['run_id'] == 'new-finance-run'
            assert rows[1]['captured_at'] != current.captured_at
            snapshot_ids = {row['charge_id'] for row in json.loads(rows[1]['rows_json'])}
            assert snapshot_ids == charge_ids
            outcomes.append({'store': 'warehouse' if index == 0 else 'postgres',
                             'earlier_unchanged': True, 'earlier': rows[0],
                             'active_reference_month': active, 'active_run_id': rows[1]['run_id'],
                             'active_captured_at': rows[1]['captured_at'],
                             'active_raw': rows[1], 'active_charge_ids': sorted(snapshot_ids)})
        if pub:
            current_summary = rs.get_subscription_summary()
            current_upcoming = rs.get_upcoming_fixed_costs_30d()
            assert (current_summary, current_upcoming) == published_before
            assert current_summary == pub.fetchall_dicts('SELECT * FROM mart_subscription_summary ORDER BY contract_name')
            assert current_upcoming == pub.fetchall_dicts('SELECT * FROM mart_upcoming_fixed_costs_30d ORDER BY expected_date, contract_name')
            assert len(current_summary) == len(current_upcoming) == 2
            assert all(row['charge_id'] is None for row in current_summary + current_upcoming)
            assert KEY not in published and UPCOMING not in published
            assert {row['charge_id'] for row in warehouse.fetchall_dicts('SELECT * FROM mart_subscription_summary')} == charge_ids
        return {'mode': 'postgres_published' if pub else 'warehouse',
                'finance_publications': list(package.publication_keys),
                'refreshed': refreshed, 'published': published,
                'published_finance_identities_still_null': bool(pub), 'snapshots': outcomes}

if __name__ == '__main__':
    observed = [run(None)]
    with running_postgres_container() as synthetic_dsn:
        observed.append(run(synthetic_dsn))
    output = Path('/tmp/hla_stage_a_promotion_observations.json')
    output.write_text(json.dumps({'observations': observed}, indent=2) + '\n')
    print(json.dumps({'result': 'pass', 'observation_file': str(output), 'modes': [x['mode'] for x in observed]}, indent=2))
