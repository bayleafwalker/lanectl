"""Native lane coordination through Vuoro's existing owner operations.

The journal is recovery state, not a work authority or an event-store replacement.
Exact pending requests survive lost acknowledgements. Only the owner grants leases
and settles outcomes; no local receipt grants effect or landing authority.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import os
import tomllib
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import uuid


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _digest(value):
    return 'sha256:' + hashlib.sha256(_json(value).encode()).hexdigest()


class CoordinationError(RuntimeError):
    """A refused or uncertain operation. Never interpret this as permission."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class VuoroClient:
    """Small stdlib invocation/v1 transport, with origin and environment checks."""

    def __init__(self, endpoint, repo_id, token_resolver, *, expected_environment=None,
                 timeout_s=30):
        parsed = urlsplit(endpoint)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in ('', '/')
                or (parsed.scheme == 'http' and parsed.hostname not in ('127.0.0.1', '::1', 'localhost'))):
            raise ValueError('endpoint must be an HTTPS origin (HTTP only for loopback)')
        if not isinstance(repo_id, str) or not repo_id:
            raise ValueError('repo_id is required')
        self.endpoint, self.repo_id = endpoint.rstrip('/'), repo_id
        self.token_resolver = token_resolver
        self.expected_environment, self.timeout_s = expected_environment, timeout_s
        self._catalog = None
        self._opener = build_opener(_NoRedirect)

    def _request(self, path, body=None):
        headers = {'X-Vuoro-Client-Protocol': '1', 'Accept': 'application/json'}
        token = self.token_resolver()
        if not isinstance(token, str) or not token or '\n' in token or '\r' in token:
            raise CoordinationError('runner credential unavailable')
        headers['Authorization'] = 'Bearer ' + token
        if body is not None:
            headers['Content-Type'] = 'application/json'
            headers['X-Request-ID'] = body['request_id']
        request = Request(self.endpoint + path, headers=headers,
                          data=None if body is None else _json(body).encode())
        try:
            with self._opener.open(request, timeout=self.timeout_s) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
                if len(raw) > 4 * 1024 * 1024:
                    raise CoordinationError('owner response too large')
                return json.loads(raw)
        except HTTPError as exc:
            try:
                code = json.loads(exc.read(8192)).get('error', {}).get('code', 'http-error')
            except (ValueError, AttributeError):
                code = 'http-error'
            raise CoordinationError(f'owner refused: {code} (HTTP {exc.code})') from None
        except (URLError, OSError, ValueError) as exc:
            raise CoordinationError('owner response unavailable or invalid; operation remains uncertain') from exc

    def discover(self):
        handshake = self._request('/api/meta/v1/handshake')
        try:
            protocol = handshake['client_protocol']
            if not protocol['minimum'] <= 1 <= protocol['maximum']:
                raise CoordinationError('incompatible owner protocol')
            if (self.expected_environment is not None
                    and handshake['environment']['name'] != self.expected_environment):
                raise CoordinationError('owner environment mismatch')
            if 'invocation/v1' not in handshake.get('invocation_schema_versions', ['invocation/v1']):
                raise CoordinationError('incompatible invocation schema')
            catalog = self._request('/api/catalog/v1')
            if not isinstance(catalog['revision'], str) or not isinstance(catalog['operations'], list):
                raise ValueError('invalid catalog')
        except (KeyError, TypeError, ValueError) as exc:
            raise CoordinationError('invalid owner discovery response') from exc
        self._catalog = catalog
        return catalog

    def envelope(self, operation, arguments, key):
        catalog = self._catalog or self.discover()
        definition = next((op for op in catalog['operations'] if op.get('name') == operation), None)
        if definition is None:
            raise CoordinationError(f'owner operation unavailable: {operation}')
        mode = definition.get('idempotency', 'not-allowed')
        if mode == 'required' and not key:
            raise CoordinationError('owner requires a transport idempotency key')
        transport_key = key if mode in ('required', 'optional') else None
        return {'schema_version': 'invocation/v1', 'request_id': str(uuid.uuid4()),
                'operation': operation, 'arguments': arguments,
                'catalog_revision': catalog['revision'], 'basis_revision': None,
                'idempotency_key': transport_key, 'repo_id': self.repo_id}

    def invoke(self, envelope):
        # Every restarted client rechecks environment before replaying any write.
        if self._catalog is None:
            self.discover()
        response = self._request('/api/invoke/v1', envelope)
        if isinstance(response, dict):
            expected = {'schema_version': 'invocation-result/v1', 'request_id': envelope['request_id'],
                        'operation': envelope['operation'], 'catalog_revision': envelope['catalog_revision']}
            if any(key in response and response[key] != value for key, value in expected.items()):
                raise CoordinationError('owner response correlation mismatch')
        if not isinstance(response, dict) or response.get('status') != 'accepted':
            code = response.get('error', {}).get('code', 'invalid-response') if isinstance(response, dict) else 'invalid-response'
            raise CoordinationError(f'owner refused: {code}')
        if not isinstance(response.get('result'), dict):
            raise CoordinationError('invalid owner result')
        return response['result']


class Coordinator:
    """One host's persisted attempt bindings and replayable owner requests."""

    def __init__(self, client, journal_path):
        self.client, self.path = client, Path(journal_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lost = {}
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS requests (key TEXT PRIMARY KEY, intent TEXT NOT NULL, envelope TEXT NOT NULL, result TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS bindings (attempt TEXT PRIMARY KEY, identity TEXT NOT NULL, binding TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS scope (identity TEXT PRIMARY KEY)')
            scope = _json([client.endpoint, client.repo_id, client.expected_environment])
            rows = db.execute('SELECT identity FROM scope').fetchall()
            if rows and rows[0][0] != scope:
                raise CoordinationError('journal belongs to a different owner/repository/environment')
            db.execute('INSERT OR IGNORE INTO scope VALUES (?)', (scope,))

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def _saved(self, key):
        with self._db() as db:
            row = db.execute('SELECT intent,envelope,result FROM requests WHERE key=?', (key,)).fetchone()
        return None if row is None else tuple(None if part is None else json.loads(part) for part in row)

    def _call(self, key, operation, intent, arguments, *, revalidate=False):
        saved = self._saved(key)
        if saved is None:
            args = arguments() if callable(arguments) else arguments
            envelope = self.client.envelope(operation, args, args.get('idempotency_key'))
            with self._db() as db:
                db.execute('INSERT OR IGNORE INTO requests VALUES (?,?,?,NULL)',
                           (key, _json(intent), _json(envelope)))
            saved = self._saved(key)
        prior, envelope, result = saved
        if prior != intent or envelope['operation'] != operation:
            raise CoordinationError('same operation key has different content')
        if result is not None and not revalidate:
            return result
        result = self.client.invoke(envelope)
        with self._db() as db:
            db.execute('UPDATE requests SET result=? WHERE key=?', (_json(result), key))
        return result

    def _binding(self, attempt):
        with self._db() as db:
            row = db.execute('SELECT binding FROM bindings WHERE attempt=?', (attempt,)).fetchone()
        if row is None:
            raise CoordinationError('attempt has no owner binding; call start first')
        return json.loads(row[0])

    def _put(self, attempt, identity, binding):
        with self._db() as db:
            prior = db.execute('SELECT identity FROM bindings WHERE attempt=?', (attempt,)).fetchone()
            if prior and prior[0] != _json(identity):
                raise CoordinationError('attempt has different work/model/profile binding')
            db.execute('INSERT OR REPLACE INTO bindings VALUES (?,?,?)',
                       (attempt, _json(identity), _json(binding)))

    def start(self, attempt_id, item_id, model_id, profile_digest, recipe_id='lanectl/v1'):
        if not isinstance(item_id, int) or isinstance(item_id, bool) or item_id <= 0:
            raise ValueError('item_id must be a positive integer')
        identity = [item_id, model_id, profile_digest, recipe_id]
        prefix = 'lanectl-' + hashlib.sha256(attempt_id.encode()).hexdigest()
        run_args = {'harness_id': 'lanectl', 'harness_build': '0.1.0', 'model_id': model_id,
                    'recipe_id': recipe_id, 'observed_profile': {'instruction_digest': profile_digest,
                    'skill_digests': []}, 'idempotency_key': prefix + '-run'}
        run = self._call(attempt_id + ':run', 'work.run.register-v1', identity, run_args)['run']['run_id']
        args = {'item_id': item_id, 'run_id': run, 'idempotency_key': prefix + '-claim'}
        lease = self._call(attempt_id + ':claim', 'work.lease.acquire-v1', identity, args, revalidate=True)['lease']
        self._check_lease(lease)
        binding = {'run_id': run, 'lease': lease, 'item_id': item_id}
        self._put(attempt_id, identity, binding)
        self._lost.pop(attempt_id, None)
        return binding

    @staticmethod
    def _check_lease(lease):
        try:
            expiry = datetime.fromisoformat(lease['expires_at'].replace('Z', '+00:00'))
            interval = lease['heartbeat_interval_seconds']
            if lease['state'] != 'active' or expiry <= datetime.now(timezone.utc):
                raise CoordinationError('owner lease expired or inactive')
            if not isinstance(interval, (int, float)) or isinstance(interval, bool) or interval <= 0:
                raise ValueError('invalid heartbeat interval')
        except (KeyError, TypeError, ValueError) as exc:
            raise CoordinationError('invalid owner lease') from exc

    def heartbeat(self, attempt_id):
        if attempt_id in self._lost:
            raise CoordinationError(self._lost[attempt_id])
        binding = self._binding(attempt_id)
        self._check_lease(binding['lease'])
        args = {'lease_id': binding['lease']['lease_id'], 'run_id': binding['run_id']}
        try:
            result = self.client.invoke(self.client.envelope('work.lease.heartbeat-v1', args, None))
            lease = result['lease']
            self._check_lease(lease)
            if lease['lease_id'] != binding['lease']['lease_id'] or lease['generation'] != binding['lease']['generation']:
                raise CoordinationError('owner changed the lease identity/generation')
            binding['lease'] = lease
            with self._db() as db:
                db.execute('UPDATE bindings SET binding=? WHERE attempt=?', (_json(binding), attempt_id))
            return lease
        except Exception as exc:
            self._lost[attempt_id] = str(exc)
            if isinstance(exc, CoordinationError):
                raise
            raise CoordinationError('heartbeat failed; authority is uncertain') from exc

    def append_evidence(self, attempt_id, key, kind, body, ref=None):
        binding = self._binding(attempt_id)
        operation_key = attempt_id + ':evidence:' + key
        intent = {'kind': kind, 'body': body, 'ref': ref}
        def arguments():
            tail = self.client.invoke(self.client.envelope('work.evidence.tail-v1',
                {'run_id': binding['run_id']}, None))['item']
            previous = None if tail is None else _digest({name: tail[name] for name in
                ('item_id', 'digest', 'chain_seq', 'chain_prev_digest')})
            return {'run_id': binding['run_id'], 'item_id': attempt_id + ':' + key,
                'kind': kind, 'ref': ref or 'lanectl:' + attempt_id, 'digest': _digest(body),
                'collector': 'lanectl/v1', 'validity': {'basis': 'indefinite',
                'valid_from': datetime.now(timezone.utc).isoformat(), 'valid_until': None,
                'component_digests': {}}, 'claims': [{'claim_type': 'observation',
                'subject': attempt_id, 'grant_id': None, 'freshness': None, 'confirms': None,
                'detail': body}], 'provenance': {}, 'chain_seq': 0 if tail is None else tail['chain_seq'] + 1,
                'chain_prev_digest': previous, 'idempotency_key': 'lane-evidence-' + hashlib.sha256(operation_key.encode()).hexdigest()}
        # Serialize tail/read/append across host processes sharing the journal.
        with self.path.with_suffix('.evidence.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return self._call(operation_key, 'work.evidence.append-v1', intent, arguments)

    def report_outcome(self, attempt_id, outcome, summary, checks=None, payload=None, *, key='outcome'):
        if outcome not in ('succeeded', 'failed'):
            raise ValueError('outcome must be succeeded or failed')
        binding = self._binding(attempt_id)
        operation_key = attempt_id + ':' + key
        args = {'lease_id': binding['lease']['lease_id'], 'run_id': binding['run_id'],
                'outcome': outcome, 'summary': summary, 'checks': checks or [], 'payload': payload or {},
                'idempotency_key': 'lane-outcome-' + hashlib.sha256(operation_key.encode()).hexdigest()}
        # An uncertain report replays its exact bytes even if it already settled
        # the lease remotely. A new report must first verify current ownership.
        if self._saved(operation_key) is None:
            self.heartbeat(attempt_id)
        return self._call(operation_key, 'work.lease.report-outcome-v1', args, args)

    def guard(self, attempt_id, *, on_lost=None):
        return LeaseGuard(self, attempt_id, on_lost=on_lost)


class LeaseGuard:
    """Heartbeat while native execution runs; cancel it on lost/uncertain authority."""

    def __init__(self, coordinator, attempt_id, *, on_lost=None):
        self.coordinator, self.attempt_id = coordinator, attempt_id
        self.on_lost = on_lost or (lambda: None)
        self._stop = threading.Event()
        self._error = None
        self._thread = None

    def _lose(self, exc):
        self._error = exc
        self.on_lost()

    def __enter__(self):
        try:
            lease = self.coordinator.heartbeat(self.attempt_id)
        except CoordinationError as exc:
            self._lose(exc)
            raise
        def beat():
            interval = lease['heartbeat_interval_seconds']
            while not self._stop.wait(interval):
                try:
                    fresh = self.coordinator.heartbeat(self.attempt_id)
                    interval = fresh['heartbeat_interval_seconds']
                except CoordinationError as exc:
                    self._lose(exc)
                    return
        self._thread = threading.Thread(target=beat, name='lanectl-heartbeat', daemon=True)
        self._thread.start()
        return self

    def assert_active(self):
        if self._error is not None:
            raise CoordinationError(str(self._error))
        self.coordinator._check_lease(self.coordinator._binding(self.attempt_id)['lease'])

    def __exit__(self, exc_type, exc, tb):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.coordinator.client.timeout_s + 1)
        if self._thread and self._thread.is_alive():
            self._lose(CoordinationError('heartbeat did not stop; authority is uncertain'))
        if exc_type is None:
            self.assert_active()


def configured(repo_name, *, root=None, journal_path=None):
    """Load opt-in protected governance; credentials are resolved only at request time.

    [repos.NAME] in governance/vuoro.toml requires endpoint, repo_id,
    expected_environment and token_env. Missing configuration disables coordination.
    """
    from .config import home
    from .events import state_dir
    config = Path(root or home()) / 'governance' / 'vuoro.toml'
    if not config.exists():
        return None
    raw = tomllib.loads(config.read_text()).get('repos', {}).get(repo_name)
    if raw is None:
        return None
    required = ('endpoint', 'repo_id', 'expected_environment', 'token_env')
    if any(not isinstance(raw.get(key), str) or not raw[key] for key in required):
        raise CoordinationError('Vuoro configuration requires endpoint, repo_id, expected_environment, token_env')
    client = VuoroClient(raw['endpoint'], raw['repo_id'], lambda: os.environ.get(raw['token_env']),
                         expected_environment=raw['expected_environment'])
    safe = hashlib.sha256(repo_name.encode()).hexdigest()[:20]
    return Coordinator(client, journal_path or state_dir() / ('coordination-' + safe + '.sqlite'))


def register(sub):
    parser = sub.add_parser('coordinate', help='inspect the configured Vuoro coordination owner')
    parser.add_argument('repo', help='repository name from governance/vuoro.toml')
    return {'coordinate': _cmd}


def _cmd(args, log):
    coordinator = configured(args.repo)
    if coordinator is None:
        print(f'{args.repo}: Vuoro coordination is not configured')
        return 1
    try:
        catalog = coordinator.client.discover()
        print(f'{args.repo}: Vuoro catalog {catalog["revision"]}; journal {coordinator.path}')
        return 0
    except CoordinationError as exc:
        print(f'{args.repo}: {exc}')
        return 1
