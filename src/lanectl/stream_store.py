"""Lanectl-owned transactional lane event stream; no work or target authority."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3

from .contracts import validate_event

SCHEMA_VERSION = 1
MAX_BATCH = 256
MAX_BYTES = 1024 * 1024


class StreamError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def initialize(path):
    """Explicit migration entrypoint. Runtime construction never runs DDL."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    try:
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, SCHEMA_VERSION):
            raise StreamError('incompatible-schema', 'lane stream schema is incompatible')
        with db:
            db.executescript('''
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS lane_events (
                  workspace TEXT NOT NULL, repo TEXT NOT NULL, stream TEXT NOT NULL,
                  revision INTEGER NOT NULL, event TEXT NOT NULL, principal TEXT NOT NULL,
                  PRIMARY KEY(workspace,repo,stream,revision));
                CREATE TABLE IF NOT EXISTS lane_batches (
                  workspace TEXT NOT NULL, repo TEXT NOT NULL, stream TEXT NOT NULL,
                  principal TEXT NOT NULL, key TEXT NOT NULL, digest TEXT NOT NULL,
                  result TEXT NOT NULL, PRIMARY KEY(workspace,repo,stream,principal,key));
                PRAGMA user_version=1;
                COMMIT;
            ''')
        db.execute('PRAGMA journal_mode=WAL')
    finally:
        db.close()


class StreamStore:
    def __init__(self, path):
        self.path = Path(path)
        with self._db() as db:
            if db.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
                raise StreamError('incompatible-schema', 'lane stream migration required')
            try:
                db.execute('SELECT workspace,repo,stream,revision,event,principal FROM lane_events LIMIT 0')
                db.execute('SELECT workspace,repo,stream,principal,key,digest,result FROM lane_batches LIMIT 0')
            except sqlite3.Error as exc:
                raise StreamError('incompatible-schema', 'lane stream tables are missing or incompatible') from exc

    @contextmanager
    def _db(self):
        try:
            db = sqlite3.connect(self.path.resolve().as_uri() + '?mode=rw', uri=True, timeout=30)
        except sqlite3.Error as exc:
            raise StreamError('store-unavailable', 'lane stream database unavailable or unmigrated') from exc
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _scope(workspace, repo, stream):
        for name, value in [('workspace', workspace), ('repo', repo), ('stream', stream)]:
            if not isinstance(value, str) or not value or len(value) > 256:
                raise StreamError('invalid-scope', f'invalid {name}')
        return workspace, repo, stream

    def read(self, workspace, repo, stream, after=0, limit=256, through=None):
        scope = self._scope(workspace, repo, stream)
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= MAX_BATCH:
            raise StreamError('invalid-cursor', 'invalid cursor or limit')
        with self._db() as db:
            db.execute('BEGIN')
            head = db.execute('SELECT COALESCE(MAX(revision),0) FROM lane_events WHERE workspace=? AND repo=? AND stream=?', scope).fetchone()[0]
            through = head if through is None else through
            if type(through) is not int or not after <= through <= head:
                raise StreamError('invalid-cursor', 'snapshot revision unavailable')
            rows = db.execute('SELECT revision,event FROM lane_events WHERE workspace=? AND repo=? AND stream=? AND revision>? AND revision<=? ORDER BY revision LIMIT ?', (*scope, after, through, limit)).fetchall()
        return {'revision': through, 'head_revision': head, 'events': [json.loads(r[1]) for r in rows],
                'next_after': rows[-1][0] if rows else after,
                'has_more': bool(rows and rows[-1][0] < through)}

    def append(self, workspace, repo, stream, principal, key, expected_revision, events):
        scope = self._scope(workspace, repo, stream)
        if not isinstance(principal, str) or not principal or not isinstance(key, str) or not 8 <= len(key) <= 128:
            raise StreamError('invalid-identity', 'principal and bounded idempotency key required')
        if type(expected_revision) is not int or expected_revision < 0:
            raise StreamError('invalid-revision', 'expected revision must be nonnegative')
        if not isinstance(events, list) or not 1 <= len(events) <= MAX_BATCH:
            raise StreamError('invalid-batch', 'batch must contain 1 to 256 events')
        try:
            encoded = encode(events)
            if len(encoded.encode()) > MAX_BYTES:
                raise ValueError('batch too large')
            frozen = json.loads(encoded)
            for event in frozen:
                if not isinstance(event, dict) or not {'schema','ts','type','item_id','data'} <= event.keys():
                    raise ValueError('event envelope is incomplete')
                validate_event(event)
        except (ValueError, TypeError, AttributeError, KeyError) as exc:
            raise StreamError('invalid-event', 'batch contains invalid lane events') from exc
        digest = hashlib.sha256(encode([expected_revision, frozen]).encode()).hexdigest()
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT digest,result FROM lane_batches WHERE workspace=? AND repo=? AND stream=? AND principal=? AND key=?', (*scope, principal, key)).fetchone()
            if prior:
                if prior[0] != digest:
                    raise StreamError('idempotency-conflict', 'same batch key has different content')
                return {**json.loads(prior[1]), 'replayed': True}
            head = db.execute('SELECT COALESCE(MAX(revision),0) FROM lane_events WHERE workspace=? AND repo=? AND stream=?', scope).fetchone()[0]
            if head != expected_revision:
                raise StreamError('revision-conflict', 'stream changed; reread before a new decision')
            for offset, event in enumerate(frozen, 1):
                db.execute('INSERT INTO lane_events VALUES (?,?,?,?,?,?)', (*scope, head + offset, encode(event), principal))
            result = {'previous_revision': head, 'revision': head + len(frozen), 'count': len(frozen), 'replayed': False}
            db.execute('INSERT INTO lane_batches VALUES (?,?,?,?,?,?,?)', (*scope, principal, key, digest, encode(result)))
            return result


def register(sub):
    parser = sub.add_parser('stream', help='explicit owner migration and lane authority configuration')
    actions = parser.add_subparsers(dest='stream_action', required=True)
    init = actions.add_parser('init', help='explicitly initialize/migrate the owner database')
    init.add_argument('database')
    backend = actions.add_parser('configure', help='select served authority for all local invocations')
    backend.add_argument('--repo', required=True)
    backend.add_argument('--home', required=True)
    backend.add_argument('--stream', default='control')
    importer = actions.add_parser('import', help='preserve validated local history in a quiesced served stream')
    importer.add_argument('--repo', required=True)
    importer.add_argument('--home', required=True)
    importer.add_argument('--stream', default='control')
    importer.add_argument('--source', required=True)
    importer.add_argument('--source-sha256', help='required exact source digest for --execute')
    importer.add_argument('--execute', action='store_true', help='append verified historical batches; default is read-only dry run')
    return {'stream': _cmd}


def _cmd(args, log):
    if args.stream_action == 'init':
        initialize(args.database)
        print(f'lane stream schema {SCHEMA_VERSION}: {args.database}')
        return 0
    from .coordination import configured
    from .events import state_dir
    from .remote_events import RemoteEventLog
    import os
    root = Path(args.home).resolve()
    coordinator = configured(args.repo, root=root)
    if coordinator is None:
        raise StreamError('owner-unconfigured', 'configure protected governance/vuoro.toml first')
    # Read-only qualification; never create or migrate the remote owner here.
    remote = RemoteEventLog(coordinator.client, state_dir() / 'stream-pending.json', stream=args.stream)
    existing = remote.read()
    if args.stream_action == 'import':
        from .contracts import validate_event
        source = Path(args.source)
        original = source.read_bytes()
        source_digest = hashlib.sha256(original).hexdigest()
        historical = [validate_event(json.loads(line)) for line in original.splitlines() if line.strip()]
        shared = min(len(existing), len(historical))
        if existing[:shared] != historical[:shared]:
            raise StreamError('history-mismatch', 'served history differs from local source')
        if not args.execute:
            print(f'dry run: source_sha256={source_digest} events={len(historical)} pending={max(0,len(historical)-len(existing))}; pause all writers before --execute')
            return 0
        if args.source_sha256 != source_digest:
            raise StreamError('source-digest-mismatch', 'exact --source-sha256 is required for import execution')
        def unchanged():
            if hashlib.sha256(source.read_bytes()).hexdigest() != source_digest:
                raise StreamError('source-changed', 'local source changed during import; keep local authority and quiesce writers')
        with source.with_suffix('.lock').open('a') as lock:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
            count = remote.import_history(historical, source_check=unchanged)
            unchanged()
            if remote.read()[:len(historical)] != historical:
                raise StreamError('history-mismatch', 'final served history verification failed')
        receipt = {'schema':'lanectl.import/v1','source_sha256':source_digest,
            'event_digest':hashlib.sha256(encode(historical).encode()).hexdigest(),'events':count,
            'endpoint':coordinator.client.endpoint,'repo_id':coordinator.client.repo_id,'stream':args.stream}
        (state_dir() / 'stream-import-receipt.json').write_text(encode(receipt))
        print(f'verified {count} historical events source_sha256={source_digest}; authority selection unchanged')
        return 0
    local = state_dir() / 'events.jsonl'
    if local.exists() and local.read_text().strip() and not existing:
        raise StreamError('import-required', 'owner stream is empty but local authority has events; import and verify before switching')
    if local.exists() and local.read_text().strip():
        historical = [json.loads(line) for line in local.read_text().splitlines() if line.strip()]
        if existing[:len(historical)] != historical:
            raise StreamError('history-mismatch', 'served stream does not preserve the local authority history')
    body = {'schema':'lanectl.backend/v1','backend':'served','repo':args.repo,
            'home':str(root),'stream':args.stream}
    marker = state_dir() / 'backend.json'
    temp = marker.with_suffix('.tmp')
    with temp.open('w') as fh:
        fh.write(encode(body))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(temp, marker)
    print(f'served lane authority selected: {args.repo}/{args.stream}; pause all writers during cutover')
    return 0
