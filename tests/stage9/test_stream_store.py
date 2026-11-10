"""The served lane owner preserves atomicity and repository isolation."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from lanectl.contracts import make_event
from lanectl.stream_store import StreamStore, StreamError, initialize


def event(item='release-x'):
    return make_event('release.published', {'release_id': item, 'revision': 1}, item_id=item)


@pytest.fixture
def store(tmp_path):
    path = tmp_path / 'stream.sqlite'
    initialize(path)
    return StreamStore(path)


def test_runtime_refuses_missing_or_unmigrated_store(tmp_path):
    with pytest.raises(StreamError):
        StreamStore(tmp_path / 'absent.sqlite')
    assert not (tmp_path / 'absent.sqlite').exists()


def test_batch_is_atomic_and_invalid_event_never_partially_appends(store):
    with pytest.raises(StreamError, match='invalid'):
        store.append('ws', 'repo', 'control', 'p', 'batch-0001', 0, [event(), {'type': 'unknown'}])
    assert store.read('ws', 'repo', 'control')['events'] == []
    store.append('ws', 'repo', 'control', 'p', 'batch-0001', 0, [event(), event('second-x')])
    assert store.read('ws', 'repo', 'control')['revision'] == 2


def test_concurrent_expected_revision_has_only_one_winner(store):
    def writer(key):
        try:
            return store.append('ws', 'repo', 'control', key, 'batch-0001', 0, [event()])['revision']
        except StreamError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        answers = list(pool.map(writer, ['p-a', 'p-b']))
    assert set(answers) == {1, 'revision-conflict'}
    assert len(store.read('ws', 'repo', 'control')['events']) == 1


def test_lost_ack_replay_and_changed_payload_refusal(store):
    e = event()
    first = store.append('ws', 'repo', 'control', 'p', 'batch-0001', 0, [e])
    second = store.append('ws', 'repo', 'control', 'p', 'batch-0001', 0, [e])
    assert second == dict(first, replayed=True)
    with pytest.raises(StreamError) as exc:
        store.append('ws', 'repo', 'control', 'p', 'batch-0001', 0, [event('changed-x')])
    assert exc.value.code == 'idempotency-conflict'


def test_read_pins_snapshot_and_scopes_workspace_repo_stream(store):
    store.append('ws', 'repo', 'control', 'p', 'batch-0001', 0, [event(), event('second-x')])
    page = store.read('ws', 'repo', 'control', limit=1)
    store.append('ws', 'repo', 'control', 'p', 'batch-0002', 2, [event('third-x')])
    tail = store.read('ws', 'repo', 'control', after=page['next_after'], through=page['revision'])
    assert len(tail['events']) == 1 and tail['revision'] == 2 and not tail['has_more']
    for scope in [('other-ws', 'repo', 'control'), ('ws', 'other-repo', 'control'), ('ws', 'repo', 'other-stream')]:
        assert store.read(*scope)['events'] == []


def test_missing_event_envelope_key_is_an_owner_refusal_not_partial_write(store):
    malformed = event()
    del malformed['item_id']
    with pytest.raises(StreamError) as exc:
        store.append('ws','repo','control','p','batch-0001',0,[event(), malformed])
    assert exc.value.code == 'invalid-event'
    assert store.read('ws','repo','control')['revision'] == 0


def test_schema_number_alone_cannot_admit_incompatible_tables(tmp_path):
    import sqlite3
    path=tmp_path/'broken.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA user_version=1')
    with pytest.raises(StreamError,match='tables are missing'):
        StreamStore(path)
