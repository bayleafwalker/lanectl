"""Extra Stage C qualification; run only against a recorded, stable UI candidate."""
from __future__ import annotations

import hashlib
import os
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

import pytest
import tests.test_attention_current_ui_acceptance as frozen
from semantic_oracle import assert_rows

EXPECTED_FROZEN = '57c9e9eef945a90d133a7a0f2b29194b1d9df7cd6a0007c52a50672b1fc02bf5'
assert hashlib.sha256(Path(frozen.__file__).read_bytes()).hexdigest() == EXPECTED_FROZEN, 'unexpected frozen acceptance bytes'
assert Path(frozen.__file__).resolve().is_relative_to(Path.cwd().resolve()), 'frozen fixture imported outside checkout'
if os.environ.get('HLA_UI_QUAL_LEDGER') and os.environ.get('HLA_UI_QUAL_TOKEN'):
    from ownership import install

    install(Path(os.environ['HLA_UI_QUAL_LEDGER']), os.environ['HLA_UI_QUAL_TOKEN'])

# Observe semantic associations from the same real browser page. The source UI
# and frozen file are untouched; this modifies only the imported scratch variable.
needle = 'console.log(JSON.stringify({status:r.status(),url:p.url(),rows,body,groups,queue}));'
assert frozen.BROWSER.count(needle) == 1, 'frozen browser contract changed; re-audit'
extractor = r'''const semantic=await p.locator('main').evaluateAll(ms=>{const main=ms[0];if(!main)return [];
 const nodes=[main,...main.querySelectorAll('li,dl,tr,table,section,article,div,p,[role="group"],[data-record-row]')];
 const pathOf=el=>{let parts=[];for(let n=el;n && n!==main;n=n.parentElement){if(!n.parentElement)break;parts.unshift(Array.prototype.indexOf.call(n.parentElement.children,n));}return 'root'+parts.map(n=>'.'+n).join('');};
 const visible=el=>!!el && el.getClientRects().length>0;
 return nodes.map(group=>{const pairs=[];const add=(label,value)=>{label=(label||'').trim();value=(value||'').trim();if(label&&value&&!pairs.some(p=>p[0]===label&&p[1]===value))pairs.push([label,value]);};
 for(const dt of group.querySelectorAll('dt')){const dd=dt.nextElementSibling;if(visible(dt)&&visible(dd)&&dd.tagName==='DD')add(dt.innerText,dd.innerText);}
 for(const tr of [group,...group.querySelectorAll('tr')]){if(tr.tagName==='TR'){const th=tr.querySelector(':scope > th');const td=tr.querySelector(':scope > td');if(visible(th)&&visible(td))add(th.innerText,td.innerText);}}
 for(const el of group.querySelectorAll('[aria-labelledby]')){if(!visible(el))continue;const ids=el.getAttribute('aria-labelledby').split(/\s+/);add(ids.map(id=>document.getElementById(id)?.innerText||'').join(' '),el.innerText);}
 for(const el of group.querySelectorAll('strong,b,label,span')){if(!visible(el)||el.children.length)continue;const label=el.innerText.trim();if(!label||label.length>80)continue;const sibling=el.nextElementSibling;if(visible(sibling))add(label,sibling.innerText);else if((el.tagName==='STRONG'||el.tagName==='B')&&visible(el.parentElement)){const parent=el.parentElement.innerText.trim();if(parent.startsWith(label))add(label,parent.slice(label.length).replace(/^\s*:?\s*/,''));}}
 return {path:pathOf(group),pairs,headings:[...(group.matches('h1,h2,h3,h4,h5,h6')?[group]:[]),...group.querySelectorAll('h1,h2,h3,h4,h5,h6')].filter(visible).map(h=>h.innerText),text:group.innerText};}).filter(group=>group.pairs.length>=2 || group.headings.length>0);});'''
frozen.BROWSER = frozen.BROWSER.replace(needle, extractor + '\n' + needle.replace('groups,queue}', 'groups,queue,semantic}'))
lab = frozen.lab


def source_rows(kind):
    common = {'currency': 'EUR'}
    return {
        'anomaly': [
            {'transaction_id': 't1', 'counterparty_name': 'Maple Ledger', 'booking_date': '2026-01-02', 'amount': '-12.3456', 'direction': 'outflow', 'anomaly_reason': 'unusual vendor', 'anomaly_type': 'amount'},
            {'transaction_id': 't1', 'counterparty_name': 'Birch Ledger', 'booking_date': '2026-02-03', 'amount': '-42.9876', 'direction': 'inflow', 'anomaly_reason': 'unusual category', 'anomaly_type': 'amount'},
        ],
        'upcoming_cost': [
            {**common, 'charge_id': 'a', 'contract_name': 'Alpha Plan', 'provider': 'Willow Provider', 'expected_amount': '12.3456', 'frequency': 'monthly', 'expected_date': '2026-03-04', 'confidence': 'high'},
            {**common, 'charge_id': 'a', 'contract_name': 'Beta Plan', 'provider': 'Cedar Provider', 'expected_amount': '42.9876', 'frequency': 'weekly', 'expected_date': '2026-03-04', 'confidence': 'low'},
        ],
        'contract_review': [
            {**common, 'contract_id': 'grid/north', 'provider': 'Oak Provider', 'utility_type': 'electricity', 'reason': 'above_market_average', 'current_price': '7.1234', 'market_reference': '17.3456', 'score': 1},
            {**common, 'contract_id': 'grid/north', 'provider': 'Pine Provider', 'utility_type': 'electricity', 'reason': 'above_market_average', 'current_price': '9.8765', 'market_reference': None, 'score': 2},
        ],
        'contract_renewal': [
            {**common, 'contract_id': 'renew/a', 'contract_name': 'Gamma Plan', 'provider': 'Aspen Provider', 'utility_type': 'electricity', 'renewal_date': '2026-05-06', 'days_until_renewal': 17, 'current_price': '2.3456'},
            {**common, 'contract_id': 'renew/a', 'contract_name': 'Delta Plan', 'provider': 'Elm Provider', 'utility_type': 'electricity', 'renewal_date': '2026-05-06', 'days_until_renewal': 17, 'current_price': '8.7654'},
        ],
    }[kind]


def test_each_public_fact_has_correct_semantic_label_and_separate_row(lab):
    state, visit = lab
    state['real_api'] = None
    state['mode'] = 'normal'
    for kind in frozen.SEGMENTS:
        item_id = f'{kind}_opaque/semantic_ä'
        rows = source_rows(kind)
        state['record'] = {'item_id': item_id, 'rows': rows}
        state['requests'].clear()
        result = visit(f'/operating-picture/attention/{kind}/{frozen.key(item_id)}')
        assert result['status'] == 200, (kind, result)
        frozen.assert_only_exact_record(state['requests'], kind, item_id)
        assert_rows(kind, rows, result['semantic'])
        if kind == 'anomaly':
            assert not any(symbol in result['body'] for symbol in ('EUR', '€', '£', '$'))


def test_real_current_api_nonnull_market_reference_preserves_value_precision(lab, tmp_path):
    import tests.postgres_test_support as pg_support
    import tests.test_attention_record_api as api_fixture
    import uvicorn
    from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
    from packages.pipelines.transformation_service import TransformationService
    from packages.storage.duckdb_store import DuckDBStore
    from packages.storage.postgres_reporting import PostgresReportingStore

    root = Path.cwd().resolve()
    for module in (api_fixture, pg_support):
        assert Path(module.__file__).resolve().is_relative_to(root), module.__file__
    assert pg_support.docker_is_available(), 'PostgreSQL is required; no skip'
    state, visit = lab
    warehouse = DuckDBStore.memory()
    ts = TransformationService(warehouse)
    api_fixture.seed(ts)
    api_fixture.refresh(ts)
    server = thread = None
    names = []
    original = subprocess.run

    def observe(args, *pos, **kwargs):
        if isinstance(args, list) and args[:2] == ['docker', 'run'] and '--name' in args:
            names.append(args[args.index('--name') + 1])
        return original(args, *pos, **kwargs)

    @contextmanager
    def required_pg():
        try:
            with patch.object(pg_support.subprocess, 'run', side_effect=observe):
                with pg_support.running_postgres_container() as dsn:
                    yield dsn
        except pytest.skip.Exception as exc:
            pytest.fail(f'PostgreSQL unavailable; no skip: {exc}', pytrace=False)
        finally:
            for name in names:
                original(['docker', 'rm', '-f', name], capture_output=True, text=True, timeout=30)
            if names:
                inv = original(['docker', 'ps', '-a', '--format', '{{.Names}}'], capture_output=True, text=True, timeout=20)
                assert len(names) == 1 and inv.returncode == 0 and names[0] not in inv.stdout.splitlines(), 'owned PG cleanup unverified'

    try:
        with required_pg() as dsn:
            pg = PostgresReportingStore(dsn)
            api_fixture.publish(ts, pg)
            pg.execute_statements([('UPDATE mart_contract_review_candidates SET market_reference = %s', ['17.3456'])])
            service = ReportingService(ts, publication_store=pg, access_mode=ReportingAccessMode.PUBLISHED)
            client = api_fixture.make_client(tmp_path, ts, service, name='market-real')
            ids = api_fixture.attention_by_type(client)['contract_review']
            expected = api_fixture.expected_records(client)
            item_id = max(ids, key=lambda value: len(expected[('contract_review', value)]))
            rows = api_fixture.get_rows(client, 'contract_review', item_id)
            assert len(rows) >= 2 and all(row['market_reference'] == '17.3456' for row in rows), rows
            assert api_fixture.canon(rows) == api_fixture.canon(expected[('contract_review', item_id)])
            port = frozen.free_port()
            server = uvicorn.Server(uvicorn.Config(client.app, host='127.0.0.1', port=port, log_level='error', lifespan='off'))
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            for _ in range(100):
                if server.started:
                    break
                assert thread.is_alive(), 'synthetic real API exited'
                time.sleep(.1)
            assert server.started, 'synthetic real API did not start'
            state['real_api'] = f'http://127.0.0.1:{port}'
            state['requests'].clear()
            result = visit('/operating-picture/attention/contract_review/' + frozen.key(item_id))
            assert result['status'] == 200, result
            requests = [unquote(path) for path in state['requests'] if '/records/' in path]
            assert requests == ['/reports/contract-review-candidates/records/' + item_id], requests
            assert_rows('contract_review', rows, result['semantic'])
    finally:
        state['real_api'] = None
        if server:
            server.should_exit = True
        if thread:
            thread.join(timeout=10)
            assert not thread.is_alive(), 'owned synthetic API did not stop'
        warehouse.close()
