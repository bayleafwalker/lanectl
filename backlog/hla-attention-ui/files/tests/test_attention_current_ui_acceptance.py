"""Browser acceptance of current-report attention using disposable synthetic services."""
from __future__ import annotations

import base64
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from contextlib import closing, contextmanager
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'apps/web/frontend'
IMAGE = 'sha256:b0ab6f3cb99aa7803adbc14d9027ec1785fc6e433b97e134e0f8fe61683b6b53'
NODE = '/projects/dev/homelab-analytics/.tooling/node-v20.20.1-linux-x64/bin'
SEGMENTS = {'anomaly': 'transaction-anomalies', 'upcoming_cost': 'upcoming-fixed-costs',
            'contract_review': 'contract-review-candidates', 'contract_renewal': 'contract-renewal-watchlist'}

# This browser program only reports observed browser state. Assertions live in Python.
BROWSER = r'''const {chromium}=require('playwright');
(async()=>{const b=await chromium.connect(process.argv[2]); const p=await b.newPage();
try { let r=await p.goto(process.argv[3],{waitUntil:'networkidle'});
if (process.argv[4]) { const a=p.locator('.attentionRow').filter({hasText:process.argv[4]}).locator('a'); if(await a.evaluate(e=>e.tabIndex)<0) throw new Error('record link is not keyboard focusable'); await a.focus(); await p.keyboard.press('Enter'); await p.waitForLoadState('networkidle'); r=await p.reload({waitUntil:'networkidle'}); }
if (process.argv[5]) { await p.locator('.attentionRow a[href="'+process.argv[5]+'"]').click(); await p.waitForLoadState('networkidle'); r=await p.reload({waitUntil:'networkidle'}); }
const rows=await p.locator('.attentionRow').evaluateAll(es=>es.map(e=>({text:e.innerText,tone:e.querySelector('.pill')?.getAttribute('data-tone'),links:Array.from(e.querySelectorAll('a')).map(a=>a.getAttribute('href'))})));
const body=await p.locator('body').innerText();
const queue=await p.locator('.attentionRow').evaluateAll(es=>es[0]?.closest('article')?.innerText || '');
const groups=await p.locator('main li, main dl, main tr, main [data-record-row]').evaluateAll(es=>es.filter(e=>!es.some(parent=>parent!==e && parent.contains(e))).map(e=>e.innerText));
console.log(JSON.stringify({status:r.status(),url:p.url(),rows,body,groups,queue}));
} finally {await b.close();}})().catch(e=>{console.error(e);process.exit(1)});'''


def free_port():
    with closing(socket.socket()) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def key(value):
    return base64.urlsafe_b64encode(value.encode('utf-8')).decode().rstrip('=')


def assert_only_exact_record(requests, kind, item_id):
    report_paths = [urllib.parse.unquote(path) for path in requests if path.startswith('/reports/')]
    expected = '/reports/' + SEGMENTS[kind] + '/records/' + item_id
    assert report_paths == [expected], (report_paths, expected)


def stop_process(proc):
    if proc and proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=10)


@pytest.fixture(scope='module')
def lab(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('attention-browser')
    assert Path(NODE, 'node').is_file(), f'Node 20 missing: {NODE}'
    env = dict(os.environ, PATH=NODE + ':' + os.environ.get('PATH', ''))
    modules = WEB / 'node_modules'
    if not (modules / 'playwright/package.json').is_file():
        install = subprocess.run(['npm', 'ci', '--prefer-offline'], cwd=WEB, env=env,
                                 text=True, capture_output=True, timeout=300)
        assert install.returncode == 0, f'locked npm ci failed: {install.stderr[-4000:]}'
    version = json.loads((modules / 'playwright/package.json').read_text())['version']
    assert version == '1.59.1', f'Playwright version mismatch: {version}'
    image = subprocess.run(['docker', 'image', 'inspect', IMAGE], capture_output=True, text=True, timeout=20)
    assert image.returncode == 0, f'matched local browser image unavailable: {image.stderr[-1000:]}'
    browser_script = tmp / 'browser.cjs'
    browser_script.write_text(BROWSER)
    state = {'rows': [], 'requests': [], 'mode': 'normal', 'record': {}, 'real_api': None}

    class Backend(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            path = parsed.path
            state['requests'].append(path)
            status, payload = 200, {'rows': []}
            if state['real_api'] and (path == '/reports/attention-items' or '/records/' in path):
                try:
                    with urllib.request.urlopen(state['real_api'] + self.path, timeout=20) as response:
                        status, payload = response.status, json.load(response)
                except urllib.error.HTTPError as exc:
                    status, payload = exc.code, json.load(exc)
            elif path == '/auth/me':
                payload = {'user': {'username': 'synthetic', 'role': 'admin'}}
            elif path == '/reports/monthly-cashflow':
                payload = {'rows': [{'booking_month': '2024-02', 'income': '100.00', 'expense': '30.00', 'net': '70.00', 'transaction_count': 1}]}
            elif path == '/control/source-freshness':
                payload = {'datasets': []}
            elif path == '/reports/attention-items':
                payload = {'rows': state['rows']}
                if state['mode'] == 'feed-unavailable':
                    status, payload = 503, {'detail': 'SYNTHETIC_SECRET'}
                elif state['mode'] == 'missing-feed':
                    payload = {}
                elif state['mode'] == 'null-feed':
                    payload = {'rows': None}
                elif state['mode'] == 'object-feed':
                    payload = {'rows': {'not': 'an array'}}
            elif '/records/' in path:
                mode = state['mode']
                if mode != 'normal':
                    status = {'unauthorized': 401, 'denied': 403, 'absent': 404,
                              'unavailable': 503, 'busy': 503, 'unexpected': 500}[mode]
                    payload = {'error': 'SYNTHETIC_SECRET', 'retry_after_seconds': 5} if mode == 'busy' else {'detail': 'SYNTHETIC_SECRET'}
                else:
                    payload = state['record']
            data = b'{' if path == '/reports/attention-items' and state['mode'] == 'invalid-json' else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            if state['mode'] == 'busy' and status == 503:
                self.send_header('Retry-After', '5')
            self.end_headers()
            self.wfile.write(data)

    backend = ThreadingHTTPServer(('127.0.0.1', 0), Backend)
    thread = threading.Thread(target=backend.serve_forever, daemon=True)
    thread.start()
    next_port, browser_port = free_port(), free_port()
    while browser_port == next_port:
        browser_port = free_port()
    env['HOMELAB_ANALYTICS_API_BASE_URL'] = f'http://127.0.0.1:{backend.server_port}'
    env['NODE_PATH'] = str(modules)
    next_log = (tmp / 'next.log').open('w')
    next_proc = None
    browser_id = None
    name = None
    try:
        build = subprocess.run(['npm', 'run', 'build'], cwd=WEB, env=env, text=True,
                               capture_output=True, timeout=300)
        (tmp / 'next-build.log').write_text(build.stdout + build.stderr)
        assert build.returncode == 0, f'Next production build failed: {build.stderr[-4000:]}'
        next_proc = subprocess.Popen([str(modules / '.bin/next'), 'start', '-H', '127.0.0.1', '-p', str(next_port)],
                                     cwd=WEB, env=env, stdout=next_log, stderr=subprocess.STDOUT,
                                     start_new_session=True)
        for _ in range(120):
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{next_port}/operating-picture', timeout=2) as response:
                    assert response.status == 200
                    break
            except (OSError, urllib.error.URLError):
                assert next_proc.poll() is None, f'Next exited: {(tmp / "next.log").read_text()[-4000:]}'
                time.sleep(1)
        else:
            raise AssertionError(f'Next startup timed out: {(tmp / "next.log").read_text()[-4000:]}')
        name = 'hla-attention-accept-' + uuid.uuid4().hex[:12]
        cidfile = tmp / 'browser.cid'
        launch = subprocess.run(['docker', 'run', '-d', '--cidfile', str(cidfile), '--name', name, '--network', 'host', '--ipc=host',
                                 '-v', str(modules) + ':/opt/node_modules:ro', IMAGE, 'node',
                                 '/opt/node_modules/playwright/cli.js', 'run-server', '--host', '127.0.0.1',
                                 '--port', str(browser_port)], capture_output=True, text=True, timeout=45)
        (tmp / 'browser-launch.log').write_text(launch.stdout + launch.stderr)
        if cidfile.exists():
            browser_id = cidfile.read_text().strip()
        assert launch.returncode == 0, f'browser launch failed: {launch.stderr}'
        assert browser_id == launch.stdout.strip(), 'browser cid mismatch'
        assert len(browser_id) == 64
        logs = ''
        for _ in range(40):
            probe = subprocess.run(['docker', 'logs', browser_id], text=True, capture_output=True, timeout=20)
            logs = probe.stdout + probe.stderr
            (tmp / 'browser-start.log').write_text(logs)
            if f'Listening on ws://127.0.0.1:{browser_port}/' in logs:
                break
            time.sleep(.5)
        else:
            raise AssertionError(f'browser startup failed: {logs}')

        def visit(path, click_title=None, click_href=None):
            result = subprocess.run(['node', str(browser_script), f'ws://127.0.0.1:{browser_port}/',
                                     f'http://127.0.0.1:{next_port}' + path, click_title or '', click_href or ''], cwd=WEB, env=env,
                                    text=True, capture_output=True, timeout=45)
            assert result.returncode == 0, f'browser failed: {result.stderr}'
            return json.loads(result.stdout)

        yield state, visit
    finally:
        cleanup_error = None
        try:
            if name and not browser_id:
                inspect = subprocess.run(['docker', 'inspect', '--format', '{{.Id}}', name], capture_output=True, text=True, timeout=20)
                if inspect.returncode == 0:
                    browser_id = inspect.stdout.strip()
            if browser_id:
                subprocess.run(['docker', 'rm', '-f', browser_id], capture_output=True, text=True, timeout=30)
                inventory = subprocess.run(['docker', 'ps', '-a', '--no-trunc', '--format', '{{.ID}}'],
                                           capture_output=True, text=True, timeout=20)
                if inventory.returncode != 0 or browser_id in inventory.stdout.splitlines():
                    cleanup_error = 'owned browser cleanup unverified'
        finally:
            try:
                stop_process(next_proc)
            finally:
                backend.shutdown()
                backend.server_close()
                thread.join(timeout=5)
                next_log.close()
        assert not thread.is_alive(), 'owned synthetic backend did not stop'
        assert cleanup_error is None, cleanup_error


def item(index, severity, kind='anomaly'):
    return {'item_id': f'{kind}_opaque/{index}_\u00e4', 'item_type': kind,
            'source_domain': 'utilities' if kind.startswith('contract') else 'finance',
            'severity': severity, 'title': f'Synthetic item {index}', 'detail': f'Independent detail {index}'}


def test_rank_is_stable_descending_before_top_eight(lab):
    state, visit = lab
    rows = [item(i, value, list(SEGMENTS)[i % len(SEGMENTS)])
            for i, value in enumerate([1, 3, 2, 1, 3, 2, 3, 1, 2, 3, 2, None])]
    state['rows'] = rows
    page = visit('/operating-picture')
    assert page['status'] == 200, page
    expected = [1, 4, 6, 9, 2, 5, 8, 10]
    observed = [next((i for i in range(len(rows)) if re.search(rf'Synthetic item {i}(?!\d)', row['text'])), None)
                for row in page['rows']]
    assert observed == expected, f'current report priority ordering before top eight: {observed} != {expected}'
    for row, i in zip(page['rows'], expected):
        assert ('urgent' if rows[i]['severity'] == 3 else 'soon') in row['text'].lower()
        assert row['tone'] == ('warn' if rows[i]['severity'] == 3 else 'warm')
    assert 'current report' in page['queue'].lower(), page['queue']
    assert 'february 2024' in page['body'].lower() and 'february 2024' not in page['queue'].lower()
    state['rows'] = list(reversed(rows))
    changed = visit('/operating-picture')
    assert changed['rows'] != page['rows'], 'ranking ignored input order mutation'


def test_unknown_priorities_are_neutral_last(lab):
    state, visit = lab
    rows = [item(100, None), item(101, '3'), item(102, 8), item(103, 1), item(104, 'bad')]
    rows.append({k: v for k, v in item(105, None).items() if k != 'severity'})
    state['rows'] = rows
    page = visit('/operating-picture')
    observed = [next((i for i in range(100, 106) if re.search(rf'Synthetic item {i}(?!\d)', row['text'])), None)
                for row in page['rows']]
    assert observed == [103, 100, 101, 102, 104, 105], f'unknown ordering: {observed}'
    assert 'watch' in page['rows'][0]['text'].lower() and page['rows'][0]['tone'] == 'neutral'
    assert all('unknown' in row['text'].lower() and row['tone'] == 'neutral' for row in page['rows'][1:])


def test_distinct_links_encode_whole_key_and_lookup(lab):
    state, visit = lab
    rows = [item(201, 3, 'contract_review'), item(202, 2, 'contract_review')]
    state['rows'] = rows
    page = visit('/operating-picture')
    hrefs = [row['links'][0] for row in page['rows']]
    assert len(set(hrefs)) == 2, f'distinct attention records share destination: {hrefs}'
    for row, href in zip(rows, hrefs):
        assert href == '/operating-picture/attention/' + row['item_type'] + '/' + key(row['item_id'])
        provider = f'Synthetic Utility {row["title"]}'
        state['record'] = {'item_id': row['item_id'], 'rows': [{'contract_id': row['item_id'], 'provider': provider, 'utility_type': 'electricity', 'reason': 'review_needed', 'current_price': '17.2500', 'currency': 'EUR', 'market_reference': None, 'score': 1}]}
        state['requests'].clear()
        detail = visit(href)
        assert detail['status'] == 200, detail
        requested = [urllib.parse.unquote(path) for path in state['requests'] if '/records/' in path]
        assert requested == ['/reports/contract-review-candidates/records/' + row['item_id']], requested
        state['requests'].clear()
        clicked = visit('/operating-picture', row['title'])
        assert urllib.parse.urlsplit(clicked['url']).path == href, clicked
        assert provider in clicked['body'], clicked
        clicked_requests = [urllib.parse.unquote(path) for path in state['requests'] if '/records/' in path]
        assert clicked_requests and all(path == '/reports/contract-review-candidates/records/' + row['item_id'] for path in clicked_requests), clicked_requests


def test_detail_error_statuses_do_not_fetch_fallback_or_leak(lab):
    state, visit = lab
    for kind in SEGMENTS:
        row = item(301, 3, kind)
        route = '/operating-picture/attention/' + kind + '/' + key(row['item_id'])
        sentinel = 'StaleGuard-' + uuid.uuid4().hex[:12]
        records = {
            'anomaly': {'transaction_id': 'tx-1', 'counterparty_name': sentinel, 'booking_date': '2026-01-02', 'amount': '7.1250', 'direction': 'outflow', 'anomaly_reason': 'large', 'anomaly_type': 'amount'},
            'upcoming_cost': {'charge_id': 'charge-1', 'contract_name': 'Fixture contract', 'provider': sentinel, 'expected_amount': '7.1250', 'currency': 'EUR', 'frequency': 'monthly', 'expected_date': '2026-01-02', 'confidence': 'high'},
            'contract_review': {'contract_id': 'contract-1', 'provider': sentinel, 'utility_type': 'electricity', 'reason': 'review_needed', 'current_price': '7.1250', 'currency': 'EUR', 'market_reference': None, 'score': 1},
            'contract_renewal': {'contract_id': 'contract-1', 'contract_name': 'Fixture contract', 'provider': sentinel, 'utility_type': 'electricity', 'renewal_date': '2026-01-02', 'days_until_renewal': 4, 'current_price': '7.1250', 'currency': 'EUR'},
        }
        state['mode'] = 'normal'
        state['record'] = {'item_id': row['item_id'], 'rows': [records[kind]]}
        positive = visit(route)
        assert positive['status'] == 200 and sentinel in positive['body'], (kind, positive)
        for mode, text in [('denied', 'denied'), ('absent', 'current report'),
                           ('unavailable', 'unavailable'), ('busy', 'unavailable')]:
            state['mode'] = mode
            state['requests'].clear()
            result = visit(route)
            body = result['body'].lower()
            assert text in body, (kind, mode, result)
            assert 'synthetic_secret' not in body and sentinel.lower() not in body and 'all clear' not in body
            if mode == 'absent':
                assert 'deleted' not in body
            assert_only_exact_record(state['requests'], kind, row['item_id'])
    state['mode'] = 'unauthorized'
    assert '/login' in visit(route)['url']
    state['mode'] = 'unexpected'
    result = visit(route)
    assert 'synthetic_secret' not in result['body'].lower()
    assert result['status'] >= 500 or any(s in result['body'].lower() for s in ('error', 'problem', 'unexpected'))
    state['mode'] = 'normal'


def test_only_a_valid_empty_feed_can_show_all_clear(lab):
    state, visit = lab
    state['rows'] = []
    state['mode'] = 'normal'
    empty = visit('/operating-picture')
    assert empty['status'] == 200 and ('all clear' in empty['body'].lower() or 'no attention' in empty['body'].lower())
    for mode in ('missing-feed', 'null-feed', 'object-feed', 'invalid-json', 'feed-unavailable'):
        state['mode'] = mode
        result = visit('/operating-picture')
        assert 'all clear' not in result['body'].lower(), (mode, result)
        assert 'no attention' not in result['body'].lower(), (mode, result)
        assert 'synthetic_secret' not in result['body'].lower(), (mode, result)
        assert result['status'] >= 500 or any(word in result['body'].lower() for word in ('unavailable', 'error', 'problem')), (mode, result)
    state['mode'] = 'normal'


def test_real_api_all_kinds_complete_rows_and_opaque_ids(lab, tmp_path):
    """The browser calls real ASGI API + reader backed by disposable PostgreSQL."""
    import uvicorn

    import tests.postgres_test_support as postgres_support
    import tests.test_attention_record_api as frozen
    from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
    from packages.pipelines.transformation_service import TransformationService
    from packages.storage.duckdb_store import DuckDBStore
    from packages.storage.postgres_reporting import PostgresReportingStore
    from tests.postgres_test_support import docker_is_available, running_postgres_container

    assert Path(frozen.__file__).resolve().is_relative_to(ROOT), frozen.__file__
    assert docker_is_available(), 'real API acceptance requires Docker/PostgreSQL; no skip'
    state, visit = lab
    store = DuckDBStore.memory()
    ts = TransformationService(store)
    frozen.seed(ts)
    frozen.refresh(ts)
    server = None
    thread = None

    @contextmanager
    def required_postgres():
        names = []
        original_run = subprocess.run

        def observe(args, *positional, **kwargs):
            if isinstance(args, list) and args[:2] == ['docker', 'run'] and '--name' in args:
                names.append(args[args.index('--name') + 1])
            return original_run(args, *positional, **kwargs)

        try:
            with patch.object(postgres_support.subprocess, 'run', side_effect=observe):
                with running_postgres_container() as dsn:
                    yield dsn
        except pytest.skip.Exception as exc:
            pytest.fail(f'PostgreSQL availability changed; no skip: {exc}', pytrace=False)
        finally:
            if names:
                for name in names:
                    original_run(['docker', 'rm', '-f', name], capture_output=True, text=True, timeout=30)
                inventory = original_run(['docker', 'ps', '-a', '--format', '{{.Names}}'],
                                         capture_output=True, text=True, timeout=20)
                assert len(names) == 1 and inventory.returncode == 0 and all(
                    name not in inventory.stdout.splitlines() for name in names
                ), 'owned PostgreSQL cleanup unverified'

    try:
        with required_postgres() as dsn:
            pg = PostgresReportingStore(dsn)
            frozen.publish(ts, pg)
            pg.execute_statements([('UPDATE mart_contract_review_candidates SET market_reference = NULL', [])])
            service = ReportingService(ts, publication_store=pg, access_mode=ReportingAccessMode.PUBLISHED)
            client = frozen.make_client(tmp_path, ts, service, name='real-api')
            by_type = frozen.attention_by_type(client)
            expected = frozen.expected_records(client)
            assert set(by_type) == set(SEGMENTS) and all(by_type.values()), by_type
            assert any(row.get('market_reference') is None for (kind, _), rows in expected.items() if kind == 'contract_review' for row in rows), 'fixture lacks null market reference'
            assert any('/' in value for values in by_type.values() for value in values), 'fixture lacks slash ID'
            selected = []
            for kind, ids in by_type.items():
                ordered = sorted(ids, key=lambda v: (len(expected[(kind, v)]), '/' in v), reverse=True)
                selected.append((kind, ordered[0]))
            assert sum(len(expected[k]) > 1 for k in selected) >= 2, 'fixture lacks two multi-row groups'
            same_kind = next((kind for kind, ids in by_type.items() if len(ids) > 1), None)
            assert same_kind is not None, 'fixture lacks distinct same-kind IDs'
            selected.append((same_kind, next(v for v in by_type[same_kind] if v != dict(selected)[same_kind])))
            slash_kind, slash_id = next((kind, item_id) for kind, item_id in selected if '/' in item_id)
            selected_ids = [item_id for _, item_id in selected]
            assert len(selected_ids) == len(set(selected_ids)) == 5
            # Bound the disposable current feed to five genuine published IDs;
            # ranking before top-eight is tested separately with >8 inputs.
            pg.execute_statements([('DELETE FROM mart_open_attention_items WHERE NOT (item_id = ANY(%s))', [selected_ids])])
            for kind, item_id in selected:
                actual_rows = frozen.get_rows(client, kind, item_id)
                assert frozen.canon(actual_rows) == frozen.canon(expected[(kind, item_id)]), (kind, item_id)
                other = next(k for k in SEGMENTS if k != kind)
                assert frozen.get_record(client, other, item_id).status_code == 404
            api_port = free_port()
            config = uvicorn.Config(client.app, host='127.0.0.1', port=api_port, log_level='error', lifespan='off')
            server = uvicorn.Server(config)
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            for _ in range(100):
                if server.started:
                    break
                assert thread.is_alive(), 'real API server exited during startup'
                time.sleep(.1)
            assert server.started, 'real API server did not start'
            state['real_api'] = f'http://127.0.0.1:{api_port}'
            for kind, item_id in selected:
                url = state['real_api'] + '/reports/' + SEGMENTS[kind] + '/records/' + urllib.parse.quote(item_id, safe='')
                with urllib.request.urlopen(url, timeout=20) as response:
                    body = json.load(response)
                    assert response.status == 200 and body['item_id'] == item_id
                    assert frozen.canon(body['rows']) == frozen.canon(expected[(kind, item_id)])
            print('real API preflight: four kinds, five distinct IDs, slash, two multirow groups, null market reference and HTTP rows verified')
            listing = visit('/operating-picture')
            links = [link for row in listing['rows'] for link in row['links']]
            for click_kind, click_id in selected:
                href = f'/operating-picture/attention/{click_kind}/{key(click_id)}'
                assert href in links, f'real API record missing distinct Next detail link: {click_kind} {links}'
                state['requests'].clear()
                clicked = visit('/operating-picture', click_href=href)
                assert urllib.parse.urlsplit(clicked['url']).path == href, clicked
                requests = [urllib.parse.unquote(path) for path in state['requests'] if '/records/' in path]
                assert requests and all(path == '/reports/' + SEGMENTS[click_kind] + '/records/' + click_id for path in requests), requests
            facts = {'anomaly': ('counterparty_name', 'booking_date', 'amount', 'direction', 'anomaly_reason'),
                     'upcoming_cost': ('contract_name', 'provider', 'expected_amount', 'currency', 'frequency', 'expected_date', 'confidence'),
                     'contract_review': ('provider', 'utility_type', 'reason', 'current_price', 'currency', 'market_reference'),
                     'contract_renewal': ('contract_name', 'provider', 'renewal_date', 'days_until_renewal', 'current_price', 'currency')}
            for kind, item_id in selected:
                path = f'/operating-picture/attention/{kind}/{key(item_id)}'
                state['requests'].clear()
                result = visit(path)
                assert result['status'] == 200, (kind, item_id, result)
                assert 'current report' in result['body'].lower()
                source_rows = expected[(kind, item_id)]
                text = result['body']
                if kind == 'anomaly':
                    assert not any(currency in text for currency in ('EUR', '€', '£', '$')), 'anomaly source has no currency'
                # Match each source component to a distinct semantic group.
                # Price strings may differ only in insignificant trailing zeros.
                from decimal import Decimal, InvalidOperation

                numeric_fields = {'amount', 'expected_amount', 'current_price', 'market_reference'}
                def contains(group, field, value):
                    if value is None:
                        return 'unknown' in group.lower()
                    if field.endswith('_date') or field == 'booking_date':
                        try:
                            day = date.fromisoformat(str(value)[:10])
                            return any(candidate.lower() in group.lower() for candidate in (day.isoformat(), day.strftime('%d %b %Y').lstrip('0'), day.strftime('%B %d, %Y').replace(' 0', ' ')))
                        except ValueError:
                            return str(value).lower() in group.lower()
                    if field == 'currency':
                        return str(value).lower() in group.lower() or {'EUR': '€', 'GBP': '£', 'USD': '$'}.get(str(value), '\0') in group
                    if field in numeric_fields:
                        try:
                            expected_number = Decimal(str(value))
                        except InvalidOperation:
                            return str(value) in group
                        for token in re.findall(r'(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])', group):
                            if Decimal(token) == expected_number:
                                return True
                        return False
                    return str(value).lower() in group.lower()

                groups = result['groups']
                used = set()
                for source_row in source_rows:
                    matches = [i for i, group in enumerate(groups) if i not in used
                               and all(contains(group, field, source_row.get(field)) for field in facts[kind])]
                    assert matches, (kind, source_row, groups)
                    used.add(matches[0])
                actual = [urllib.parse.unquote(v) for v in state['requests'] if '/records/' in v]
                assert actual == ['/reports/' + SEGMENTS[kind] + '/records/' + item_id], actual
                assert not any(phrase in text.lower() for phrase in ('observed today', 'estimated savings', 'you should'))
            other = next(kind for kind in SEGMENTS if kind != slash_kind)
            state['requests'].clear()
            mismatch = visit(f'/operating-picture/attention/{other}/{key(slash_id)}')
            assert 'current report' in mismatch['body'].lower() and 'not found' in mismatch['body'].lower(), mismatch
            requests = [urllib.parse.unquote(path) for path in state['requests'] if '/records/' in path]
            assert requests == ['/reports/' + SEGMENTS[other] + '/records/' + slash_id], requests
    finally:
        state['real_api'] = None
        if server:
            server.should_exit = True
        if thread:
            thread.join(timeout=10)
            assert not thread.is_alive(), 'owned API server did not stop'
        store.close()


def test_invalid_route_identifiers_never_reach_backend(lab):
    state, visit = lab
    state['mode'] = 'normal'
    for path in ('/operating-picture/attention/not-a-kind/' + key('review_valid'),
                 '/operating-picture/attention/anomaly/%%%',
                 '/operating-picture/attention/anomaly/YQ==',
                 '/operating-picture/attention/anomaly/YR'):
        state['requests'].clear()
        result = visit(path)
        assert result['status'] == 404 or 'not found' in result['body'].lower(), (path, result)
        assert not any('/records/' in req for req in state['requests']), state['requests']


def test_request_oracle_rejects_fallback_wrong_identity_and_double_encoding():
    item_id = 'contract_opaque/雪_underscore'
    route = '/reports/contract-review-candidates/records/'
    encoded = urllib.parse.quote(item_id, safe='')
    assert_only_exact_record([route + encoded], 'contract_review', item_id)
    broken = ([route + encoded, '/reports/attention-items'],
              [route + urllib.parse.quote(encoded, safe='')],
              [route + urllib.parse.quote(item_id + '_different', safe='')])
    for requests in broken:
        with pytest.raises(AssertionError):
            assert_only_exact_record(requests, 'contract_review', item_id)


def test_real_api_source_authorization_contract(tmp_path):
    import tests.test_attention_record_api as frozen

    assert Path(frozen.__file__).resolve().is_relative_to(ROOT), frozen.__file__
    frozen.test_source_publication_permission_reads_only_its_own_segment(tmp_path)
    frozen.test_attention_only_permission_never_exposes_source_records(tmp_path)
    frozen.test_missing_or_invalid_bearer_is_rejected(tmp_path)


EXPECTED_CASES = {
    'test_rank_is_stable_descending_before_top_eight',
    'test_unknown_priorities_are_neutral_last',
    'test_distinct_links_encode_whole_key_and_lookup',
    'test_detail_error_statuses_do_not_fetch_fallback_or_leak',
    'test_only_a_valid_empty_feed_can_show_all_clear',
    'test_real_api_all_kinds_complete_rows_and_opaque_ids',
    'test_invalid_route_identifiers_never_reach_backend',
    'test_real_api_source_authorization_contract',
    'test_request_oracle_rejects_fallback_wrong_identity_and_double_encoding',
}


def validate_report(report):
    root = ET.parse(report).getroot()
    if root.tag not in ('testsuite', 'testsuites'):
        raise ValueError('unexpected JUnit root')
    suites = list(root.iter('testsuite'))
    cases = list(root.iter('testcase'))
    names = [case.get('name') for case in cases]
    if len(suites) != 1 or len(cases) != len(EXPECTED_CASES) or set(names) != EXPECTED_CASES:
        raise ValueError(f'incomplete or unexpected selection: {names!r}')
    if any(case.get('classname') != 'tests.test_attention_current_ui_acceptance' for case in cases):
        raise ValueError('unexpected test module')
    suite = suites[0]
    for name, expected in (('tests', len(EXPECTED_CASES)), ('skipped', 0), ('failures', 0), ('errors', 0)):
        if int(suite.attrib[name]) != expected:
            raise ValueError(f'invalid {name} count')
    if any(list(root.iter(tag)) for tag in ('skipped', 'failure', 'error')):
        raise ValueError('JUnit contains a skip, error or failure')


def main():
    with tempfile.TemporaryDirectory(prefix='attention-ui-junit-') as directory:
        report = Path(directory) / 'results.xml'
        command = [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
                   str(Path(__file__).relative_to(ROOT)), '--junitxml', str(report)]
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode:
            return result.returncode if 0 < result.returncode < 256 else 1
        try:
            validate_report(report)
        except (OSError, ET.ParseError, KeyError, ValueError) as exc:
            print(f'UI acceptance incomplete: {exc}', file=sys.stderr)
            return 1
        print('UI acceptance: all nine named cases passed without skips')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
