"""HTTP assertions; expected groups come solely from parameter-bound reporting SQL."""
import collections
import json
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import quote

SEGMENTS = {'anomaly': 'transaction-anomalies', 'contract_review': 'contract-review-candidates',
            'contract_renewal': 'contract-renewal-watchlist', 'upcoming_cost': 'upcoming-fixed-costs'}
SOURCES = {'anomaly': ('mart_transaction_anomalies_current', "'anomaly_' || transaction_id"),
           'contract_review': ('mart_contract_review_candidates', "'review_' || contract_id || '_' || reason"),
           'contract_renewal': ('mart_contract_renewal_watchlist', "'renewal_' || contract_id || '_' || CAST(renewal_date AS VARCHAR)"),
           'upcoming_cost': ('mart_upcoming_fixed_costs_30d', "'upcoming_' || charge_id || '_' || CAST(expected_date AS VARCHAR)")}

def jsonable(v):
    if isinstance(v, Decimal): return str(v)
    if isinstance(v, (date, datetime)): return v.isoformat()
    if isinstance(v, dict): return {k: jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)): return [jsonable(x) for x in v]
    return v

def canon(rows):
    return collections.Counter(json.dumps(jsonable(r), sort_keys=True, separators=(',', ':')) for r in rows)

def sql_rows(db, kind, key):
    table, expr = SOURCES[kind]
    return db.execute('select * from reporting.' + table + ' where ' + expr + ' = %s', (key,)).fetchall()

def verify(db, items, request, unauth_request, models):
    assert set(models) == set(SOURCES) == set(SEGMENTS)
    assert {i['item_type'] for i in items} == set(SOURCES), 'missing kind fixture'
    ids = [i['item_id'] for i in items]
    assert len(ids) == len(set(ids)), 'duplicate item ids'
    status, feed = request('/reports/attention-items')
    assert status == 200 and isinstance(feed, dict) and isinstance(feed.get('rows'), list), 'feed failed'
    feed_ids = [row['item_id'] for row in feed['rows']]
    assert len(feed_ids) == len(set(feed_ids)) and set(feed_ids) == set(ids), 'feed ids differ'
    groups = []
    for item in items:
        kind, key = item['item_type'], item['item_id']
        rows = sql_rows(db, kind, key)
        assert rows, (kind, key, 'empty independent SQL group')
        expected = [models[kind].model_validate(jsonable(row)).model_dump(mode='json') for row in rows]
        path = '/reports/' + SEGMENTS[kind] + '/records/' + quote(key, safe='')
        status, body = request(path)
        assert status == 200, (kind, key, 'status', status)
        assert isinstance(body, dict) and set(body) == {'item_id', 'rows'}, (kind, key, 'shape')
        assert body['item_id'] == key and isinstance(body['rows'], list), (kind, key, 'identity/rows')
        assert canon(body['rows']) == canon(expected), (kind, key, 'rows differ')
        groups.append({'type': kind, 'id': key, 'rows': len(expected)})
    # Independently prove the chosen opaque key is absent from each source.
    unknown = '__hla_smoke_provably_unknown_7f937b01__'
    for kind in SOURCES:
        assert not sql_rows(db, kind, unknown), 'unknown control collides'
        path = '/reports/' + SEGMENTS[kind] + '/records/' + quote(unknown, safe='')
        status, body = request(path)
        assert status == 404 and isinstance(body, dict) and set(body) == {'detail'}, (kind, 'unknown control', status)
    first = items[0]
    path = '/reports/' + SEGMENTS[first['item_type']] + '/records/' + quote(first['item_id'], safe='')
    status, body = unauth_request(path)
    assert status == 401 and isinstance(body, dict) and set(body) == {'detail'}, ('unauthenticated control', status)
    return {'http_ids': sorted(ids), 'http_groups': groups,
            'slash_groups': [g for g in groups if '/' in g['id']],
            'multirow_groups': [g for g in groups if g['rows'] > 1],
            'unknown_404_kinds': sorted(SOURCES), 'unauthenticated_401': True}
