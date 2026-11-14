#!/usr/bin/env python3
"""Seed disposable synthetic attention data through production transformation/reporting APIs.

Local default: /tmp warehouse and SQLite control plane. For a synthetic Postgres
reporting store, pass an explicit DSN and a unique synthetic_attention_* schema.
The contract ID containing '/' enters through the normalized contract-price
loader; the CSV adapter generates hashed contract IDs instead.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import timedelta
from pathlib import Path

import psycopg
from psycopg import sql

from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
from packages.pipelines.transformation_service import TransformationService
from packages.storage.duckdb_store import DuckDBStore
from packages.storage.ingestion_config import IngestionConfigRepository
from packages.storage.postgres_reporting import PostgresReportingStore

PUBLICATIONS = [
    'mart_subscription_summary', 'mart_upcoming_fixed_costs_30d',
    'mart_contract_price_current', 'mart_contract_review_candidates',
    'mart_contract_renewal_watchlist', 'mart_transaction_anomalies_current',
    'mart_open_attention_items',
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('/tmp/hla-attention-synthetic-seed'))
    parser.add_argument('--source-commit', required=True,
                        help='Caller-supplied full 40-character source revision (not verified by helper)')
    parser.add_argument('--postgres-dsn', help='Explicit disposable Postgres reporting DSN')
    parser.add_argument('--postgres-schema', help='Unique synthetic_attention_* reporting schema')
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9a-fA-F]{40}', args.source_commit):
        parser.error('--source-commit must be exactly 40 hexadecimal characters')
    root = args.root.resolve()
    if not root.is_relative_to(Path('/tmp')) or root == Path('/tmp'):
        parser.error('--root must be a dedicated directory under /tmp')
    if root.exists() and any(root.iterdir()):
        parser.error('--root must not contain existing data')
    if args.postgres_dsn:
        if not args.postgres_schema or not re.fullmatch(r'synthetic_attention_[a-z0-9_]+', args.postgres_schema):
            parser.error('--postgres-schema must be a unique synthetic_attention_* identifier')
    elif args.postgres_schema:
        parser.error('--postgres-schema requires --postgres-dsn')
    if args.postgres_dsn:
        try:
            with psycopg.connect(args.postgres_dsn) as connection:
                connection.execute(sql.SQL('CREATE SCHEMA {}').format(
                    sql.Identifier(args.postgres_schema)
                ))
        except psycopg.errors.DuplicateSchema:
            parser.error('--postgres-schema already exists; choose a fresh schema')
    root.mkdir(parents=True, exist_ok=True)
    # The control plane and warehouse are explicitly local; no ambient settings are read.
    control = IngestionConfigRepository(root / 'control.db')
    warehouse = DuckDBStore.open(str(root / 'warehouse.duckdb'))
    service = TransformationService(warehouse, control_plane_store=control)
    today = warehouse.fetchall('SELECT CURRENT_DATE')[0][0]
    subscriptions = [
        {'contract_id': 'synthetic-sub', 'service_name': 'Synthetic Same', 'provider': 'Demo',
         'billing_cycle': 'weekly', 'amount': '10', 'currency': 'EUR',
         'start_date': str(today - timedelta(days=days)), 'end_date': None}
        for days in (14, 7)
    ]
    service.load_subscriptions(subscriptions, run_id='synthetic-subscriptions')
    prices = [
        {'contract_id': 'synthetic/utility', 'contract_name': 'Synthetic Electric',
         'provider': 'Demo Power', 'contract_type': 'electricity', 'price_component': component,
         'billing_cycle': 'monthly', 'unit_price': '1', 'currency': 'EUR',
         'quantity_unit': 'kWh', 'valid_from': str(today - timedelta(days=400)),
         'valid_to': str(today + timedelta(days=days))}
        for component, days in (('energy', 10), ('transfer', 10), ('tax', 20))
    ]
    prices.append({**prices[0], 'contract_id': 'synthetic-other', 'contract_name': 'Other',
                   'price_component': 'energy'})
    service.load_contract_prices(prices, run_id='synthetic-contract-prices')
    service.load_transactions([
        {'booked_at': str(today), 'account_id': 'synthetic-bank', 'counterparty_name': 'New Vendor',
         'amount': '-1000', 'currency': 'EUR', 'description': 'Synthetic purchase'}
    ], run_id='synthetic-transactions')
    refreshed = service.refresh_publications(PUBLICATIONS)
    postgres = PostgresReportingStore(args.postgres_dsn, schema=args.postgres_schema) if args.postgres_dsn else None
    reporting = ReportingService(service, publication_store=postgres,
        access_mode=ReportingAccessMode.PUBLISHED if postgres else ReportingAccessMode.WAREHOUSE)
    published = reporting.publish_publications(PUBLICATIONS) if postgres else reporting.record_warehouse_publications(PUBLICATIONS, run_id='synthetic-seed')
    items = reporting.get_open_attention_items()
    counts = Counter((row['item_type'], row['source_domain']) for row in items)
    expected = {'anomaly', 'contract_review', 'contract_renewal', 'upcoming_cost'}
    assert {kind for kind, _ in counts} == expected
    assert len({row['item_id'] for row in items}) == len(items)
    payments = [row for row in items if row['item_type'] == 'upcoming_cost']
    assert len(payments) == 2 and payments[0]['item_id'] != payments[1]['item_id']
    slash_items = [row for row in items if 'synthetic/utility' in row['item_id']]
    assert slash_items and all(row['source_domain'] == 'utilities' for row in slash_items)
    result = {'caller_supplied_source_commit': args.source_commit, 'reference_date': str(today), 'storage': 'postgres_published' if postgres else 'duckdb_local',
              'warehouse': str(root / 'warehouse.duckdb'), 'control_plane': str(root / 'control.db'),
              'postgres_schema': args.postgres_schema, 'refreshed': refreshed, 'published': published,
              'counts': [{'item_type': k, 'domain': d, 'count': n} for (k, d), n in sorted(counts.items())],
              'upcoming_item_ids': [row['item_id'] for row in payments],
              'slash_source': 'normalized contract-price loader: contract_id=synthetic/utility',
              'slash_item_ids': [row['item_id'] for row in slash_items]}
    (root / 'observations.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
