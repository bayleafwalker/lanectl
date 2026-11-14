"""Independent acceptance for the four-kind authenticated record boundary."""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
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
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'apps/web/frontend'
NODE = ''
PINNED_MODULES = WEB / 'node_modules'
DEPS_TMP = None
IMAGE = 'sha256:b0ab6f3cb99aa7803adbc14d9027ec1785fc6e433b97e134e0f8fe61683b6b53'
SEGMENTS = {'anomaly': 'transaction-anomalies', 'upcoming_cost': 'upcoming-fixed-costs',
            'contract_review': 'contract-review-candidates', 'contract_renewal': 'contract-renewal-watchlist'}
MARKER = 'synthetic_session=boundary-cookie-marker'
SECRET = 'SYNTHETIC_SECRET_must_not_escape'

# These routes are placed only in an isolated temporary frontend copy.
INFRA_ROUTE = '''import { backendRequest } from "@/lib/backend";
export const dynamic = "force-dynamic";
export async function GET() {
  const r = await backendRequest("get", "/reports/attention-items");
  return Response.json({status: r.status, data: await r.json()});
}
'''
BOUNDARY_ROUTE = '''import { getAttentionRecord } from "@/lib/attention-record";
import { isRedirectError } from "next/dist/client/components/redirect";
export const dynamic = "force-dynamic";
export async function GET(request: Request) {
  const u = new URL(request.url);
  const kind: unknown = JSON.parse(u.searchParams.get("kind") || "null");
  const key: unknown = JSON.parse(u.searchParams.get("key") || "null");
  try { return Response.json({result: await getAttentionRecord(kind, key)}); }
  catch (e) {
    if (isRedirectError(e)) throw e;
    return Response.json({thrown: true, message: e instanceof Error ? e.message : String(e)}, {status: 500});
  }
}
'''
CODEC_PAGE = '''"use client";
import { useEffect } from "react";
import { encodeAttentionKey, decodeAttentionKey, isAttentionRecordKind } from "@/lib/attention-key";
export default function Probe() {
  useEffect(() => { (window as any).attentionBoundaryCodec = {encodeAttentionKey, decodeAttentionKey, isAttentionRecordKind}; }, []);
  return <main>Codec probe ready</main>;
}
'''


def ensure_tools():
    global NODE, PINNED_MODULES, DEPS_TMP
    node = shutil.which('node')
    if not node:
        candidates = sorted((ROOT / '.tooling').glob('node-v20*/bin/node'))
        node = str(candidates[-1]) if candidates else None
    assert node and Path(node).is_file(), 'Node 20 unavailable on PATH or checkout tooling'
    version = subprocess.run([node, '--version'], capture_output=True, text=True, timeout=10)
    assert version.returncode == 0 and version.stdout.startswith('v20.'), 'Node 20 is required'
    NODE = str(Path(node).parent)
    if not (PINNED_MODULES / 'next/package.json').is_file():
        assert Path(NODE, 'npm').is_file() or shutil.which('npm'), 'npm unavailable'
        DEPS_TMP = tempfile.TemporaryDirectory(prefix='hla-boundary-deps-')
        deps = Path(DEPS_TMP.name)
        for name in ('package.json', 'package-lock.json'):
            shutil.copy2(WEB / name, deps / name)
        env = dict(os.environ, PATH=NODE + ':' + os.environ.get('PATH', ''))
        result = subprocess.run(['npm', 'ci', '--no-audit', '--no-fund'], cwd=deps, env=env, capture_output=True, text=True, timeout=300)
        assert result.returncode == 0, 'locked npm ci failed: ' + result.stderr[-3000:]
        PINNED_MODULES = deps / 'node_modules'
    assert (PINNED_MODULES / 'next/package.json').is_file(), 'frontend dependencies unavailable'


def require_modules():
    for name in ('attention-key.ts', 'attention-record.ts'):
        assert (WEB / 'lib' / name).is_file(), f'MISSING_REQUIRED_BOUNDARY_MODULE: lib/{name}'


def port():
    with closing(socket.socket()) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def key(value):
    return base64.urlsafe_b64encode(value.encode('utf-8')).decode().rstrip('=')


def http(url, cookie=MARKER):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    request = urllib.request.Request(url, headers={'Cookie': cookie})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def stop(proc):
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

    if proc:
        try:
            os.killpg(proc.pid, 0)
        except ProcessLookupError:
            return
        except PermissionError as exc:
            raise AssertionError('Next process group cleanup unverified') from exc
        raise AssertionError('Next process group remains alive; cleanup unverified')


class Lab:
    """Owns a temporary Next copy and dynamic local synthetic HTTP producer."""
    def __init__(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.tmp = tmp_path
        self.state = {'hits': [], 'status': 200, 'body': None, 'retry': None, 'proxy': None, 'records': None}
        self.proc = self.server = self.thread = self.log = None
        self.handlers = {}

    def __enter__(self):
        ensure_tools()
        self.copy = self.tmp / 'web'
        shutil.copytree(WEB, self.copy, ignore=shutil.ignore_patterns('node_modules', '.next', 'test-results', 'playwright-report'))
        (self.copy / 'node_modules').symlink_to(PINNED_MODULES, target_is_directory=True)
        for route, source in (('acceptance-infra/route.ts', INFRA_ROUTE), ('acceptance-boundary/route.ts', BOUNDARY_ROUTE), ('acceptance-codec/page.tsx', CODEC_PAGE)):
            target = self.copy / 'app' / route
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source)
        for sig in (signal.SIGINT, signal.SIGTERM):
            self.handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, lambda _number, _frame: (_ for _ in ()).throw(KeyboardInterrupt()))
        state = self.state

        class Producer(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                parsed = urllib.parse.urlsplit(self.path)
                state['hits'].append({'method': self.command, 'raw': parsed.path,
                                      'cookie_ok': state.get('cookie_expected', MARKER) in self.headers.get('Cookie', '')})
                if state['proxy']:
                    request = urllib.request.Request(state['proxy'] + self.path, headers={'Cookie': self.headers.get('Cookie', '')})
                    try:
                        with urllib.request.urlopen(request, timeout=20) as response:
                            status, payload = response.status, response.read()
                    except urllib.error.HTTPError as exc:
                        status, payload = exc.code, exc.read()
                else:
                    status = state['status']
                    body = state['body'] if state['body'] is not None else {'rows': []}
                    if state['records'] is not None and '/records/' in parsed.path and status == 200 and state['body'] is None:
                        if parsed.path in state['records']:
                            body = state['records'][parsed.path]
                        else:
                            status, body = 404, {'detail': 'not found'}
                    payload = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                if state['retry'] is not None:
                    self.send_header('Retry-After', state['retry'])
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        try:
            self.server = ThreadingHTTPServer(('127.0.0.1', 0), Producer)
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            self.next_port = port()
            env = dict(os.environ, PATH=NODE + ':' + os.environ.get('PATH', ''),
                       HOMELAB_ANALYTICS_API_BASE_URL=f'http://127.0.0.1:{self.server.server_port}')
            self.log = (self.tmp / 'next.log').open('w')
            self.proc = subprocess.Popen([str(PINNED_MODULES / '.bin/next'), 'dev', '-H', '127.0.0.1', '-p', str(self.next_port)],
                                         cwd=self.copy, env=env, stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)
            for _ in range(120):
                try:
                    status, _, _ = http(self.url('/acceptance-infra'))
                    if status == 200:
                        break
                except OSError:
                    pass
                assert self.proc.poll() is None, f'Next preflight exited: {(self.tmp / "next.log").read_text()[-3000:]}'
                time.sleep(1)
            else:
                raise AssertionError(f'Next preflight failed: {(self.tmp / "next.log").read_text()[-3000:]}')
            self.state['hits'].clear()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        try:
            stop(self.proc)
        finally:
            if self.server:
                self.server.shutdown()
                self.server.server_close()
            if self.thread:
                self.thread.join(timeout=5)
            if self.log:
                self.log.close()
            for sig, handler in self.handlers.items():
                signal.signal(sig, handler)
        assert not self.thread or not self.thread.is_alive(), 'synthetic producer did not stop'

    def url(self, path):
        return f'http://127.0.0.1:{self.next_port}' + path

    def call(self, kind, route_key, cookie=MARKER):
        query = urllib.parse.urlencode({'kind': json.dumps(kind), 'key': json.dumps(route_key)})
        return http(self.url('/acceptance-boundary?' + query), cookie)

    def exact_hit(self, kind, item_id):
        expected = '/reports/' + SEGMENTS[kind] + '/records/' + urllib.parse.quote(item_id, safe='')
        assert len(self.state['hits']) == 1, self.state['hits']
        hit = self.state['hits'][0]
        assert hit['method'] == 'GET' and hit['raw'] == expected and hit['cookie_ok'], hit


def test_00_existing_next_transport_fixture_is_real(tmp_path):
    with Lab(tmp_path) as lab:
        status, _, body = http(lab.url('/acceptance-infra'))
        assert status == 200 and json.loads(body)['status'] == 200
        assert lab.state['hits'] == [{'method': 'GET', 'raw': '/reports/attention-items', 'cookie_ok': True}]
        lab.state['hits'].clear()
        http(f'http://127.0.0.1:{lab.server.server_port}/reports/transaction-anomalies/records/YR')
        with pytest.raises(AssertionError):
            assert lab.state['hits'] == [], 'invalid-key injected request must be detected'


def test_10_strict_codec_node_and_browser(tmp_path):
    require_modules()
    ensure_tools()
    # Compile actual candidate TypeScript to runnable Node code, never substitute a codec.
    output = tmp_path / 'compiled'
    source = tmp_path / 'actual-codec'
    source.mkdir()
    shutil.copy2(WEB / 'lib/attention-key.ts', source / 'attention-key.ts')
    (source / 'node_modules').symlink_to(PINNED_MODULES, target_is_directory=True)
    command = [str(PINNED_MODULES / '.bin/tsc'), str(source / 'attention-key.ts'), '--target', 'ES2022',
               '--module', 'commonjs', '--moduleResolution', 'node', '--lib', 'ES2022,DOM',
               '--types', 'node', '--skipLibCheck', '--outDir', str(output)]
    env = dict(os.environ, PATH=NODE + ':' + os.environ.get('PATH', ''))
    compiled = subprocess.run(command, cwd=source, env=env, capture_output=True, text=True, timeout=90)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    module = output / 'attention-key.js'
    assert module.is_file(), 'actual codec compile did not produce JS'
    values = ['anomaly_a/b_%_雪', 'review_grid/north_ä', 'upcoming_two__id', 'renewal_🙂/x']
    invalid = ['', 'YQ==', 'YR', 'a', 'bad+', '_w', 'wK8', '7aCA', None, 4, []]
    runner = '''const m=require(process.argv[1]); const v=JSON.parse(process.argv[2]);
const out={encoded:v.values.map(x=>m.encodeAttentionKey(x)),decoded:v.values.map(x=>m.decodeAttentionKey(m.encodeAttentionKey(x))),invalid:v.invalid.map(x=>m.decodeAttentionKey(x)),kinds:v.kinds.map(x=>m.isAttentionRecordKind(x))};
for(const x of ["",42,null,{},[],"\\ud800","\\udc00"]){try{m.encodeAttentionKey(x);out.reject=false}catch(e){if(!(e instanceof TypeError))throw e;}} console.log(JSON.stringify(out));'''
    inputs = {'values': values, 'invalid': invalid, 'kinds': [*SEGMENTS, 'other', None, 1]}
    run = subprocess.run(['node', '-e', runner, str(module), json.dumps(inputs)], cwd=WEB, env=env, text=True, capture_output=True, timeout=30)
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)
    assert result.get('reject', True) is True
    assert result['encoded'] == [key(value) for value in values] and result['decoded'] == values
    assert result['invalid'] == [None] * len(invalid)
    assert result['kinds'] == [True] * 4 + [False] * 3
    browser_codec(tmp_path, inputs, result)


def browser_codec(tmp_path, inputs, expected):
    assert json.loads((PINNED_MODULES / 'playwright/package.json').read_text())['version'] == '1.59.1'
    with Lab(tmp_path / 'browser-lab') as lab:
        js = tmp_path / 'browser.cjs'
        js.write_text('''const {chromium}=require('playwright');(async()=>{const b=process.argv[2]==='local'?await chromium.launch({headless:true}):await chromium.connect(process.argv[2]);const p=await b.newPage();try{await p.goto(process.argv[3]);await p.waitForFunction(()=>!!window.attentionBoundaryCodec);const r=await p.evaluate(v=>{const m=window.attentionBoundaryCodec;const o={encoded:v.values.map(x=>m.encodeAttentionKey(x)),decoded:v.values.map(x=>m.decodeAttentionKey(m.encodeAttentionKey(x))),invalid:v.invalid.map(x=>m.decodeAttentionKey(x)),kinds:v.kinds.map(x=>m.isAttentionRecordKind(x))};for(const x of ["",42,null,{},[],"\\ud800","\\udc00"]){try{m.encodeAttentionKey(x);o.reject=false}catch(e){if(!(e instanceof TypeError))throw e;}}return o},JSON.parse(process.argv[4]));console.log(JSON.stringify(r));}finally{await b.close()}})().catch(e=>{console.error(e);process.exit(1)});''')
        env = dict(os.environ, PATH=NODE + ':' + os.environ.get('PATH', ''), NODE_PATH=str(PINNED_MODULES))
        endpoint = os.environ.get('HLA_BOUNDARY_PLAYWRIGHT_WS')
        if not endpoint:
            preflight = subprocess.run(['node', '-e', "const {chromium}=require('playwright');chromium.launch({headless:true}).then(async b=>{await b.close()}).catch(e=>{console.error(e);process.exit(1)})"], env=env, text=True, capture_output=True, timeout=45)
            if preflight.returncode == 0:
                endpoint = 'local'
            else:
                (tmp_path / 'local-browser-preflight.log').write_text(preflight.stdout + preflight.stderr)
        if endpoint:
            result = subprocess.run(['node', str(js), endpoint, lab.url('/acceptance-codec'), json.dumps(inputs)], env=env, text=True, capture_output=True, timeout=60)
            assert result.returncode == 0, result.stderr
            assert json.loads(result.stdout) == expected
            return
        image = subprocess.run(['docker', 'image', 'inspect', IMAGE], capture_output=True, text=True, timeout=20)
        assert image.returncode == 0, 'local Chromium and matched browser image unavailable'
        browser_port = port()
        owner = uuid.uuid4().hex
        name = 'hla-boundary-accept-' + owner[:12]
        cidfile = tmp_path / 'browser.cid'
        cid = None
        try:
            launch = subprocess.run(['docker', 'run', '-d', '--cidfile', str(cidfile), '--name', name,
                                     '--label', 'hla-boundary.owner=' + owner, '--network', 'host', '--ipc=host', '-v', str(PINNED_MODULES) + ':/opt/node_modules:ro',
                                     IMAGE, 'node', '/opt/node_modules/playwright/cli.js', 'run-server',
                                     '--host', '127.0.0.1', '--port', str(browser_port)], capture_output=True, text=True, timeout=45)
            (tmp_path / 'browser-launch.log').write_text(launch.stdout + launch.stderr)
            if cidfile.exists():
                cid = cidfile.read_text().strip()
            assert launch.returncode == 0 and cid == launch.stdout.strip(), 'browser failed to start'
            for _ in range(40):
                logs = subprocess.run(['docker', 'logs', cid], capture_output=True, text=True, timeout=20)
                (tmp_path / 'browser-start.log').write_text(logs.stdout + logs.stderr)
                if 'Listening on' in logs.stdout + logs.stderr:
                    break
                time.sleep(.5)
            else:
                raise AssertionError('browser startup failed')
            env = dict(os.environ, PATH=NODE + ':' + os.environ.get('PATH', ''), NODE_PATH=str(PINNED_MODULES))
            result = subprocess.run(['node', str(js), f'ws://127.0.0.1:{browser_port}/', lab.url('/acceptance-codec'), json.dumps(inputs)], env=env, text=True, capture_output=True, timeout=60)
            assert result.returncode == 0, result.stderr
            assert json.loads(result.stdout) == expected
        finally:
            # The unique name and label also cover interruption during docker run
            # before the cidfile is written; refuse to remove a mismatched owner.
            inspect = subprocess.run(['docker', 'inspect', '--format', '{{.Id}} {{index .Config.Labels "hla-boundary.owner"}}', name], capture_output=True, text=True, timeout=20)
            inventory = subprocess.run(['docker', 'ps', '-a', '--no-trunc', '--format', '{{.ID}} {{.Names}}'], capture_output=True, text=True, timeout=20)
            assert inventory.returncode == 0, 'browser daemon inventory unavailable'
            entries = [line.split(' ', 1) for line in inventory.stdout.splitlines()]
            matching = [item for item in entries if len(item) == 2 and item[1] == name]
            if matching:
                parts = inspect.stdout.strip().split()
                assert inspect.returncode == 0 and len(parts) == 2 and parts[1] == owner and parts[0] == matching[0][0], 'browser ownership unverified'
                cid = parts[0]
                removed = subprocess.run(['docker', 'rm', '-f', cid], capture_output=True, timeout=30)
                assert removed.returncode == 0, 'browser cleanup failed'
            inventory = subprocess.run(['docker', 'ps', '-a', '--no-trunc', '--format', '{{.ID}} {{.Names}}'], capture_output=True, text=True, timeout=20)
            assert inventory.returncode == 0 and all(line.split(' ', 1)[-1] != name for line in inventory.stdout.splitlines()), 'browser cleanup unverified'


TYPECHECK = r'''import { getAttentionRecord, type AttentionRecordResult, type AttentionSafeRow, type AttentionPublicRows } from "@/lib/attention-record";
import { encodeAttentionKey, decodeAttentionKey, isAttentionRecordKind } from "@/lib/attention-key";
async function prove(kind: unknown, key: unknown) {
  const literal = await getAttentionRecord("anomaly", "YWJj");
  if (literal.status === "ok") {
    const field: string | null | undefined = literal.rows[0]?.counterparty_name;
    void field;
    // @ts-expect-error anomaly has no market reference
    literal.rows[0]?.market_reference;
    // @ts-expect-error anomaly rows are not review rows
    const wrong: AttentionSafeRow<AttentionPublicRows["contract_review"]>[] = literal.rows;
    void wrong;
  }
  const unknown = await getAttentionRecord(kind, key);
  if (unknown.status === "ok") {
    switch (unknown.kind) {
      case "anomaly": { const x: string | null | undefined = unknown.rows[0]?.counterparty_name; void x; break; }
      case "upcoming_cost": { const x: string | null | undefined = unknown.rows[0]?.charge_id; void x; break; }
      case "contract_review": { const x: string | null | undefined = unknown.rows[0]?.market_reference; void x; break; }
      case "contract_renewal": { const x: number | null | undefined = unknown.rows[0]?.contract_duration_days; void x; break; }
    }
  }
  const all: AttentionRecordResult = unknown; void all;
  const encoded: string = encodeAttentionKey("x"); const decoded: string | null = decodeAttentionKey(encoded);
  void decoded; void isAttentionRecordKind(kind);
}
void prove;
'''


def test_20_typescript_discriminated_result_and_falsifiers(tmp_path):
    require_modules()
    ensure_tools()
    copy = tmp_path / 'web'
    shutil.copytree(WEB, copy, ignore=shutil.ignore_patterns('node_modules', '.next', 'test-results', 'playwright-report'))
    (copy / 'node_modules').symlink_to(PINNED_MODULES, target_is_directory=True)
    probe = copy / 'acceptance-type-probe.ts'
    config = copy / 'tsconfig.acceptance.json'
    config.write_text(json.dumps({'extends': './tsconfig.json', 'compilerOptions': {'incremental': False},
                                  'files': ['acceptance-type-probe.ts'], 'include': []}))
    env = dict(os.environ, PATH=NODE + ':' + os.environ.get('PATH', ''))

    def compile_source(source):
        probe.write_text(source)
        return subprocess.run([str(PINNED_MODULES / '.bin/tsc'), '--noEmit', '-p', str(config)], cwd=copy,
                              env=env, capture_output=True, text=True, timeout=90)

    good = compile_source(TYPECHECK)
    assert good.returncode == 0, good.stdout + good.stderr
    markers = re.findall(r'// @ts-expect-error [^\n]+', TYPECHECK)
    assert len(markers) == 2
    for marker in markers:
        bad = compile_source(TYPECHECK.replace(marker, '// removed for independent type falsifier', 1))
        assert bad.returncode != 0 and re.search(r'TS\d+', bad.stdout + bad.stderr), 'wrong-kind type falsifier passed'


def fixture_rows(kind, suffix):
    return {
        'anomaly': {'transaction_id': suffix, 'counterparty_name': 'Vendor ' + suffix, 'booking_date': '2026-02-03',
                    'amount': '-12.3456', 'direction': 'outflow', 'anomaly_reason': 'reason-' + suffix, 'anomaly_type': 'amount'},
        'upcoming_cost': {'charge_id': None, 'contract_name': 'Plan ' + suffix, 'provider': 'Provider ' + suffix,
                          'expected_amount': '9.8765', 'currency': 'EUR', 'frequency': 'monthly',
                          'expected_date': '2026-02-03', 'confidence': 'high'},
        'contract_review': {'contract_id': suffix, 'provider': 'Provider ' + suffix, 'utility_type': 'electricity',
                            'reason': 'reason-' + suffix, 'current_price': '8.1234', 'currency': 'EUR',
                            'market_reference': None, 'score': 2},
        'contract_renewal': {'contract_id': suffix, 'contract_name': 'Plan ' + suffix, 'provider': 'Provider ' + suffix,
                             'utility_type': 'electricity', 'renewal_date': '2026-02-03', 'days_until_renewal': 42,
                             'current_price': '7.4567', 'currency': 'EUR', 'contract_duration_days': None},
    }[kind]


def outcome(lab, kind, item_id):
    return lab.call(kind, key(item_id))


def test_30_full_authorized_transport_and_mutations(tmp_path):
    require_modules()
    with Lab(tmp_path) as lab:
        lab.state['records'] = {}
        ids = {kind: f'{kind}_part/雪_%_whole' for kind in SEGMENTS}
        ids2 = {kind: f'{kind}_part/ä_%_other' for kind in SEGMENTS}
        for kind, item_id in [*ids.items(), ('contract_review', ids2['contract_review'])]:
            one = fixture_rows(kind, item_id)
            two = fixture_rows(kind, item_id + '-variant')
            rows = [one, one.copy(), two]
            raw = '/reports/' + SEGMENTS[kind] + '/records/' + urllib.parse.quote(item_id, safe='')
            lab.state['records'][raw] = {'item_id': item_id, 'rows': rows}
            lab.state['hits'].clear()
            status, _, body = outcome(lab, kind, item_id)
            assert status == 200, body
            assert json.loads(body)['result'] == {'status': 'ok', 'kind': kind, 'item_id': item_id, 'rows': rows}
            lab.exact_hit(kind, item_id)
            # Mutating actual producer data must change output, preserving missing and null.
            mutated = [dict(one)]
            field = next(k for k, value in mutated[0].items() if isinstance(value, str) and k not in {'currency'})
            mutated[0][field] = 'mutation-' + item_id
            lab.state['records'][raw] = {'item_id': item_id, 'rows': mutated}
            lab.state['hits'].clear()
            status, _, body = outcome(lab, kind, item_id)
            assert status == 200 and json.loads(body)['result']['rows'] == mutated
            lab.exact_hit(kind, item_id)
        for kind, item_id in ids.items():
            other = next(k for k in SEGMENTS if k != kind)
            lab.state['hits'].clear()
            status, _, body = outcome(lab, other, item_id)
            assert status == 200 and json.loads(body)['result']['status'] == 'not_found'
            lab.exact_hit(other, item_id)
        for kind, route_key in [('bad-kind', key('valid')), ('anomaly', 'YR'), ('anomaly', 'YQ=='), (None, key('valid')), ('anomaly', None)]:
            lab.state['hits'].clear()
            status, _, body = lab.call(kind, route_key)
            assert status == 200 and json.loads(body)['result']['status'] == 'invalid', body
            assert lab.state['hits'] == [], lab.state['hits']


def test_40_status_redirect_and_sanitized_failures(tmp_path):
    require_modules()
    with Lab(tmp_path) as lab:
        item_id = 'review_opaque/雪_%_safe'
        for status, retry, expected in [(403, None, 'denied'), (404, None, 'not_found'), (503, None, 'unavailable'),
                                        (503, '12', 'unavailable'), (503, 'Wed, 21 Oct 2015 07:28:00 GMT', 'unavailable'),
                                        (503, 'not-a-date', 'unavailable'), (503, '-1', 'unavailable')]:
            lab.state.update(status=status, body={'detail': SECRET}, retry=retry)
            lab.state['hits'].clear()
            code, _, payload = outcome(lab, 'contract_review', item_id)
            assert code == 200 and SECRET.encode() not in payload
            result = json.loads(payload)['result']
            assert result['status'] == expected
            if status == 503:
                expected_retry = retry if retry in ('12', 'Wed, 21 Oct 2015 07:28:00 GMT') else None
                assert result['retryAfter'] == expected_retry
            lab.exact_hit('contract_review', item_id)
        lab.state.update(status=401, body={'detail': SECRET}, retry=None)
        lab.state['hits'].clear()
        code, headers, payload = outcome(lab, 'contract_review', item_id)
        assert code in (303, 307, 308) and urllib.parse.urlsplit(headers['Location']).path == '/login', (code, headers)
        assert SECRET.encode() not in payload
        lab.exact_hit('contract_review', item_id)
        lab.state.update(status=500, body={'detail': SECRET}, retry=None)
        lab.state['hits'].clear()
        code, _, payload = outcome(lab, 'contract_review', item_id)
        assert code == 500 and json.loads(payload)['thrown'] is True
        assert SECRET.encode() not in payload and item_id.encode() not in payload
        lab.exact_hit('contract_review', item_id)
        lab.server.shutdown()
        lab.server.server_close()
        lab.thread.join(timeout=5)
        lab.server = lab.thread = None
        code, _, payload = outcome(lab, 'contract_review', item_id)
        assert code == 500 and json.loads(payload)['thrown'] is True and SECRET.encode() not in payload


def test_50_malformed_success_fails_closed(tmp_path):
    require_modules()
    item_id = 'review_proto/雪_%_identity'
    valid = fixture_rows('contract_review', 'fixture')
    cases = [
        b'{', None, [], 'scalar', 23, {}, {'item_id': item_id}, {'rows': []},
        {'item_id': item_id, 'rows': None}, {'item_id': item_id, 'rows': {}},
        {'item_id': 'wrong-id', 'rows': [valid]}, {'item_id': item_id, 'rows': [None]},
        {'item_id': item_id, 'rows': [[]]}, {'item_id': item_id, 'rows': ['row']},
        {'item_id': item_id, 'rows': [dict(valid, unexpected_field=SECRET)]},
        {'item_id': item_id, 'rows': [dict(valid, score='not-a-number')]},
        {'item_id': item_id, 'rows': [dict(valid, current_price=8.1234)]},
        {'item_id': item_id, 'rows': [valid], 'extra': SECRET},
    ]
    with Lab(tmp_path) as lab:
        for raw in cases:
            # None is encoded as actual JSON null, not the lab's unset sentinel.
            lab.state.update(status=200, body=b'null' if raw is None else raw, retry=None)
            lab.state['hits'].clear()
            status, _, body = outcome(lab, 'contract_review', item_id)
            assert status == 500 and json.loads(body).get('thrown') is True, (raw, status, body)
            assert SECRET.encode() not in body and item_id.encode() not in body
            lab.exact_hit('contract_review', item_id)
        for kind, field, invalid_value in (('anomaly', 'amount', 4), ('upcoming_cost', 'expected_amount', 4),
                                            ('contract_review', 'score', 'bad'), ('contract_renewal', 'days_until_renewal', 'bad')):
            malformed = dict(fixture_rows(kind, 'fixture'), **{field: invalid_value})
            lab.state.update(status=200, body={'item_id': item_id, 'rows': [malformed]})
            lab.state['hits'].clear()
            status, _, body = outcome(lab, kind, item_id)
            assert status == 500 and json.loads(body).get('thrown') is True, (kind, status, body)
            assert SECRET.encode() not in body and item_id.encode() not in body
            lab.exact_hit(kind, item_id)
        for rows in ([], [{'provider': None, 'market_reference': None}], [{'provider': 'partial'}]):
            lab.state.update(status=200, body={'item_id': item_id, 'rows': rows})
            lab.state['hits'].clear()
            status, _, body = outcome(lab, 'contract_review', item_id)
            assert status == 200 and json.loads(body)['result'] == {'status': 'ok', 'kind': 'contract_review', 'item_id': item_id, 'rows': rows}
            lab.exact_hit('contract_review', item_id)


def test_60_request_oracle_falsifiers():
    item_id = 'review_x/雪_%_whole'
    expected = '/reports/contract-review-candidates/records/' + urllib.parse.quote(item_id, safe='')
    lab = object.__new__(Lab)
    lab.state = {'hits': [{'method': 'GET', 'raw': expected, 'cookie_ok': True}]}
    lab.exact_hit('contract_review', item_id)
    bad = [
        [{'method': 'GET', 'raw': expected, 'cookie_ok': True}, {'method': 'GET', 'raw': '/reports/attention-items', 'cookie_ok': True}],
        [{'method': 'GET', 'raw': expected.replace('contract-review-candidates', 'upcoming-fixed-costs'), 'cookie_ok': True}],
        [{'method': 'GET', 'raw': expected.replace('%2F', '%252F'), 'cookie_ok': True}],
        [{'method': 'GET', 'raw': expected.rsplit('%2F', 1)[0], 'cookie_ok': True}],
        [{'method': 'GET', 'raw': expected, 'cookie_ok': False}],
    ]
    for hits in bad:
        lab.state['hits'] = hits
        with pytest.raises(AssertionError):
            lab.exact_hit('contract_review', item_id)
    expected_result = {'status': 'ok', 'kind': 'contract_review', 'item_id': item_id,
                       'rows': [fixture_rows('contract_review', 'one'), fixture_rows('contract_review', 'two')]}
    for changed in (
        dict(expected_result, item_id='other-id'),
        dict(expected_result, rows=expected_result['rows'][:1]),
        dict(expected_result, rows=list(reversed(expected_result['rows']))),
    ):
        with pytest.raises(AssertionError):
            assert changed == expected_result
    for status, payload in ((200, {'result': {'status': 'unavailable'}}), (200, {'result': {'status': 'ok'}})):
        with pytest.raises(AssertionError):
            assert status == 500 and payload.get('thrown') is True
    for status, location in ((200, '/login'), (307, '/wrong'), (500, '/login')):
        with pytest.raises(AssertionError):
            assert status in (303, 307, 308) and location == '/login'
    # The invalid-input no-fetch control must fail when a request is injected.
    hits = [{'method': 'GET', 'raw': expected, 'cookie_ok': True}]
    with pytest.raises(AssertionError):
        assert hits == []


def test_70_real_local_published_api_with_signed_session(tmp_path):
    require_modules()
    import uvicorn

    import tests.test_attention_record_api as source_fixture
    from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
    from packages.pipelines.transformation_service import TransformationService
    from packages.storage.auth_store import UserRole
    from packages.storage.duckdb_store import DuckDBStore
    from tests.test_api_auth import _build_client

    assert Path(source_fixture.__file__).resolve().is_relative_to(ROOT), source_fixture.__file__
    store = DuckDBStore.memory()
    ts = TransformationService(store)
    source_fixture.seed(ts)
    source_fixture.refresh(ts)
    publication = source_fixture.DuckPublicationStore()
    source_fixture.publish(ts, publication)
    # Synthetic in-memory publication mutation exercises a nullable public field.
    publication.store.execute('UPDATE mart_contract_review_candidates SET market_reference = NULL')
    reporting = ReportingService(ts, publication_store=publication, access_mode=ReportingAccessMode.PUBLISHED)
    api_root = tmp_path / 'api'
    api_root.mkdir()
    client = _build_client(str(api_root), users=(('boundary-reader', 'synthetic-password', UserRole.ADMIN),), reporting_service=reporting)
    login = client.post('/auth/login', json={'username': 'boundary-reader', 'password': 'synthetic-password'})
    assert login.status_code == 200
    session = client.cookies.get('homelab_analytics_session')
    assert session, 'synthetic signed local session not established'
    cookie = 'homelab_analytics_session=' + session
    by_type = source_fixture.attention_by_type(client)
    expected = source_fixture.expected_records(client)
    assert any(row.get('market_reference') is None for (kind, _), rows in expected.items() if kind == 'contract_review' for row in rows)
    assert set(by_type) == set(SEGMENTS) and all(by_type.values())
    assert any('/' in value for values in by_type.values() for value in values)
    selected = [(kind, max(ids, key=lambda value: (len(expected[(kind, value)]), '/' in value))) for kind, ids in by_type.items()]
    assert sum(len(expected[pair]) > 1 for pair in selected) >= 2
    review = dict(selected)['contract_review']
    assert len(by_type['contract_review']) > 1
    selected.append(('contract_review', next(value for value in by_type['contract_review'] if value != review)))
    if not any('/' in value for _, value in selected):
        selected.append(next((kind, value) for kind, values in by_type.items() for value in values if '/' in value))
    assert any('/' in value for _, value in selected)
    api_port = port()
    server = uvicorn.Server(uvicorn.Config(client.app, host='127.0.0.1', port=api_port, log_level='error', lifespan='off'))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            assert thread.is_alive(), 'real API failed to start'
            time.sleep(.1)
        assert server.started
        with Lab(tmp_path / 'next') as lab:
            lab.state['proxy'] = f'http://127.0.0.1:{api_port}'
            lab.state['cookie_expected'] = cookie
            for kind, item_id in selected:
                lab.state['hits'].clear()
                status, _, body = lab.call(kind, key(item_id), cookie)
                assert status == 200, body
                rows = expected[(kind, item_id)]
                assert json.loads(body)['result'] == {'status': 'ok', 'kind': kind, 'item_id': item_id, 'rows': rows}
                lab.exact_hit(kind, item_id)
            lab.state['hits'].clear()
            status, headers, _ = lab.call('contract_review', key(review), 'invalid_session=synthetic')
            assert status in (303, 307, 308) and urllib.parse.urlsplit(headers['Location']).path == '/login'
            assert len(lab.state['hits']) == 1
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        assert not thread.is_alive(), 'synthetic API did not stop'
        store.close()
        publication.store.close()


EXPECTED = {
    'test_00_existing_next_transport_fixture_is_real', 'test_10_strict_codec_node_and_browser',
    'test_20_typescript_discriminated_result_and_falsifiers', 'test_30_full_authorized_transport_and_mutations',
    'test_40_status_redirect_and_sanitized_failures', 'test_50_malformed_success_fails_closed',
    'test_60_request_oracle_falsifiers', 'test_70_real_local_published_api_with_signed_session',
}


def validate_report(path):
    root = ET.parse(path).getroot()
    suites, cases = list(root.iter('testsuite')), list(root.iter('testcase'))
    names = [case.get('name') for case in cases]
    assert root.tag in ('testsuite', 'testsuites') and len(suites) == 1
    assert len(cases) == len(EXPECTED) and set(names) == EXPECTED, names
    assert all(case.get('classname') == 'tests.test_attention_record_boundary_acceptance' for case in cases)
    assert all(int(suites[0].attrib[k]) == v for k, v in (('tests', len(EXPECTED)), ('skipped', 0), ('failures', 0), ('errors', 0)))
    assert not any(list(root.iter(tag)) for tag in ('skipped', 'failure', 'error'))


def main():
    # No bounded subprocess supervisor: pytest executes in this process. Lab and
    # browser scopes own their cleanup, including SIGINT/SIGTERM interruption.
    with tempfile.TemporaryDirectory(prefix='hla-boundary-junit-') as directory:
        report = Path(directory) / 'report.xml'
        status = pytest.main(['-q', '-p', 'no:cacheprovider', str(Path(__file__).relative_to(ROOT)), '--junitxml', str(report)])
        if status:
            return int(status)
        try:
            validate_report(report)
        except (OSError, ET.ParseError, KeyError, ValueError, AssertionError) as exc:
            print(f'boundary acceptance incomplete: {exc}', file=sys.stderr)
            return 1
        print('boundary acceptance: all eight named tests passed without skips')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
