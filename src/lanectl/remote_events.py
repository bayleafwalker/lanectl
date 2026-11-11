"""Served lane events behind append/read/locked, using optimistic batch commits."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import threading
import uuid

from .contracts import make_event, validate_event
from .coordination import CoordinationError
from .stream_store import encode


class StreamConflict(CoordinationError):
    """No batch was committed; recompute the decision from a fresh stream."""


class RemoteEventLog:
    """Owner stream adapter. A locked block commits all its appends atomically.

    The server's expected-revision CAS fences competing hosts. A conflict raises
    before admission returns a claim; callers may retry deterministic admission,
    never replay external effects automatically. Local pending bytes survive a
    lost response and are replayed using the same owner idempotency key.
    """

    def __init__(self, client, recovery_path, *, stream='control'):
        self.client, self.path, self.stream = client, Path(recovery_path), stream
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._mutex = threading.RLock()
        self._transaction = False
        self._buffer = []
        self._events = []
        self._revision = 0

    @contextmanager
    def _local_lock(self):
        with self._mutex, self.path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def _persist(self, body):
        tmp = self.path.with_name(self.path.name + '.tmp')
        with tmp.open('w') as fh:
            fh.write(encode(body))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)
        fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _recover(self):
        if not self.path.exists():
            return
        pending = json.loads(self.path.read_text())
        if (pending['endpoint'] != self.client.endpoint or pending['repo_id'] != self.client.repo_id
                or pending.get('expected_environment') != getattr(self.client, 'expected_environment', None)
                or pending['envelope']['arguments']['stream'] != self.stream):
            raise CoordinationError('pending lane batch belongs to a different owner')
        try:
            result = self.client.invoke(pending['envelope'])
        except CoordinationError as exc:
            if 'owner refused: revision-conflict' in str(exc):
                self.path.unlink()
                raise StreamConflict('lane stream changed; reread and recompute admission') from exc
            raise
        expected = pending['envelope']['arguments']['expected_revision']
        count = len(pending['envelope']['arguments']['events'])
        if (result.get('previous_revision') != expected
                or result.get('revision') != expected + count or result.get('count') != count):
            raise CoordinationError('owner batch receipt does not match submitted events')
        self.path.unlink()

    def _read_remote(self, *, after=0):
        if type(after) is not int or after < 0:
            raise CoordinationError('lane stream cursor must be a nonnegative integer')
        events, cursor, revision = [], after, None
        while True:
            args = {'stream': self.stream, 'after': cursor, 'limit': 256}
            if revision is not None:
                args['through'] = revision
            page = self.client.invoke(self.client.envelope('lane.stream.read-v1', args, None))
            if revision is None:
                revision = page['revision']
            batch, next_cursor = page['events'], page['next_after']
            if page['revision'] != revision or next_cursor != cursor + len(batch):
                raise CoordinationError('lane stream snapshot/cursor mismatch')
            events.extend(validate_event(event) for event in batch)
            cursor = next_cursor
            if not page['has_more']:
                if cursor != revision:
                    raise CoordinationError('lane stream snapshot is incomplete')
                return events, revision
            if not batch:
                raise CoordinationError('lane stream pagination did not advance')

    @contextmanager
    def locked(self):
        with self._local_lock():
            if self._transaction:
                raise CoordinationError('nested lane stream transactions are unsupported')
            self._recover()
            self._events, self._revision = self._read_remote()
            self._buffer = []
            self._transaction = True
            try:
                yield self
                if self._buffer:
                    args = {'stream': self.stream, 'expected_revision': self._revision,
                            'events': self._buffer, 'idempotency_key': 'lane-batch-' + uuid.uuid4().hex}
                    envelope = self.client.envelope('lane.stream.append-v1', args, None)
                    self._persist({'endpoint': self.client.endpoint, 'repo_id': self.client.repo_id,
                                   'expected_environment': getattr(self.client, 'expected_environment', None),
                                   'envelope': envelope})
                    self._recover()
            finally:
                self._transaction = False
                self._buffer = []

    def append(self, etype, data, *, item_id=None):
        with self._mutex:
            if self._transaction:
                event = make_event(etype, data, item_id=item_id)
                self._buffer.append(json.loads(encode(event)))
                return event
            with self.locked():
                return self.append(etype, data, item_id=item_id)

    def read(self, *, after=0):
        with self._mutex:
            if type(after) is not int or after < 0:
                raise CoordinationError('lane stream cursor must be a nonnegative integer')
            if self._transaction:
                return json.loads(encode((self._events + self._buffer)[after:]))
            with self._local_lock():
                self._recover()
                events, _ = self._read_remote(after=after)
                return events

    def import_history(self, events, *, source_check=None):
        """Preserve validated historical bytes during an explicit, quiesced cutover."""
        frozen = [validate_event(json.loads(encode(event))) for event in events]
        while True:
            if source_check:
                source_check()
            with self.locked():
                existing = self.read()
                shared = min(len(existing), len(frozen))
                if existing[:shared] != frozen[:shared]:
                    raise CoordinationError('served lane history differs from import source')
                if len(existing) >= len(frozen):
                    return len(frozen)
                self._buffer.extend(frozen[len(existing):len(existing) + 256])
