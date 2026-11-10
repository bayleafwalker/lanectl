"""Remote append/read/locked semantics through the real lane owner store."""
from contextlib import contextmanager
from pathlib import Path

import pytest

from lanectl.coordination import CoordinationError
from lanectl.remote_events import RemoteEventLog, StreamConflict
from lanectl.stream_store import StreamStore, StreamError, initialize


class Client:
    endpoint = 'https://synthetic.invalid'
    repo_id = 'repo-a'

    def __init__(self, store):
        self.store = store
        self.drop = False
        self.before_append = None

    def envelope(self, operation, arguments, key):
        return {'operation': operation, 'arguments': arguments}

    def invoke(self, envelope):
        a = envelope['arguments']
        if envelope['operation'].endswith('read-v1'):
            return self.store.read('ws', self.repo_id, a['stream'], a['after'], a['limit'], a.get('through'))
        if self.before_append:
            fn, self.before_append = self.before_append, None
            fn()
        try:
            result = self.store.append('ws', self.repo_id, a['stream'], 'p', a['idempotency_key'],
                                       a['expected_revision'], a['events'])
        except StreamError as exc:
            raise CoordinationError('owner refused: ' + exc.code) from exc
        if self.drop:
            self.drop = False
            raise CoordinationError('connection lost after commit')
        return result


@pytest.fixture
def client(tmp_path):
    initialize(tmp_path / 'owner.sqlite')
    return Client(StreamStore(tmp_path / 'owner.sqlite'))


def publish(log, item='release-x'):
    log.append('release.published', {'release_id': item, 'revision': 1}, item_id=item)


def test_atomic_block_and_uncommitted_read_projection(client, tmp_path):
    log = RemoteEventLog(client, tmp_path / 'recovery.json')
    with log.locked():
        publish(log)
        publish(log, 'second-x')
        assert len(log.read()) == 2
        assert client.store.read('ws', 'repo-a', 'control')['events'] == []
    assert len(log.read()) == 2
    with pytest.raises(RuntimeError):
        with log.locked():
            publish(log, 'third-x')
            raise RuntimeError('abort')
    assert len(log.read()) == 2


def test_lost_ack_recovery_after_restart_does_not_duplicate(client, tmp_path):
    path = tmp_path / 'recovery.json'
    client.drop = True
    with pytest.raises(CoordinationError):
        publish(RemoteEventLog(client, path))
    assert path.exists()
    log = RemoteEventLog(client, path)
    assert len(log.read()) == 1
    assert not path.exists()
    assert client.store.read('ws', 'repo-a', 'control')['revision'] == 1


def test_cross_host_conflict_cannot_return_a_claim_or_overwrite_winner(client, tmp_path):
    log = RemoteEventLog(client, tmp_path / 'recovery.json')
    other = RemoteEventLog(client, tmp_path / 'other-host.json')
    client.before_append = lambda: publish(other, 'other-x')
    with pytest.raises(StreamConflict):
        with log.locked():
            publish(log, 'loser-x')
    assert [e['item_id'] for e in log.read()] == ['other-x']
    assert not log.path.exists()


def test_pagination_reads_complete_snapshot(client, tmp_path):
    log = RemoteEventLog(client, tmp_path / 'recovery.json')
    for wave in range(2):
        with log.locked():
            for n in range(150):
                publish(log, f'item-{wave}-{n}')
    assert len(log.read()) == 300


def test_factory_marker_prevents_silent_local_fallback(tmp_path, monkeypatch):
    import json
    from lanectl.events import open_log, EventLog
    monkeypatch.setenv('LANECTL_STATE', str(tmp_path))
    monkeypatch.delenv('LANECTL_STREAM_REPO', raising=False)
    assert isinstance(open_log(), EventLog)
    (tmp_path / 'backend.json').write_text(json.dumps({'schema':'lanectl.backend/v1',
        'backend':'served','repo':'missing','home':str(tmp_path),'stream':'control'}))
    with pytest.raises(CoordinationError, match='configuration is missing'):
        open_log()
    assert (tmp_path / 'events.jsonl').read_text() == ''


def test_historical_import_preserves_original_events_and_resumes(client, tmp_path):
    from lanectl.contracts import make_event
    history = [make_event('release.published', {'release_id':f'old-{n}', 'revision':1},
               item_id=f'old-{n}', ts='2026-01-01T00:00:00Z') for n in range(300)]
    log = RemoteEventLog(client, tmp_path / 'recovery.json')
    assert log.import_history(history) == 300
    assert log.import_history(history) == 300
    assert log.read() == history
    history[0]['ts'] = 'changed'
    with pytest.raises(CoordinationError, match='differs'):
        log.import_history(history)


def test_import_refuses_local_source_drift_before_any_batch(client,tmp_path):
    from lanectl.contracts import make_event
    history = [make_event('release.published', {'release_id':'release-x','revision':1},item_id='release-x')]
    log = RemoteEventLog(client,tmp_path/'pending.json')
    def drift():
        raise CoordinationError('source changed')
    with pytest.raises(CoordinationError,match='source changed'):
        log.import_history(history,source_check=drift)
    assert log.read() == []


def test_import_cli_dry_run_hash_check_execute_and_repeat(client,tmp_path,monkeypatch):
    import hashlib
    import json
    from types import SimpleNamespace
    from lanectl import coordination, stream_store
    from lanectl.contracts import make_event
    monkeypatch.setenv('LANECTL_STATE',str(tmp_path/'host-state'))
    monkeypatch.setattr(coordination,'configured',lambda *a,**kw: SimpleNamespace(client=client))
    source=tmp_path/'source.jsonl'
    event=make_event('release.published',{'release_id':'old-x','revision':1},item_id='old-x')
    source.write_text(json.dumps(event)+'\n')
    args=SimpleNamespace(stream_action='import',home=str(tmp_path),repo='repo-a',stream='control',
                         source=str(source),source_sha256=None,execute=False)
    assert stream_store._cmd(args,None)==0
    assert client.store.read('ws','repo-a','control')['events']==[]
    args.execute=True
    with pytest.raises(stream_store.StreamError,match='source-sha256'):
        stream_store._cmd(args,None)
    args.source_sha256=hashlib.sha256(source.read_bytes()).hexdigest()
    assert stream_store._cmd(args,None)==0
    assert stream_store._cmd(args,None)==0
    assert client.store.read('ws','repo-a','control')['events']==[event]
    assert not (tmp_path/'host-state/backend.json').exists()
    receipt=json.loads((tmp_path/'host-state/stream-import-receipt.json').read_text())
    assert receipt['source_sha256']==args.source_sha256 and receipt['events']==1


def test_remote_append_and_read_snapshot_cannot_be_mutated_after_recording(client,tmp_path):
    log=RemoteEventLog(client,tmp_path/'pending.json')
    data={'release_id':'release-x','revision':1}
    with log.locked():
        returned=log.append('release.published',data,item_id='release-x')
        data['revision']=99
        returned['data']['revision']=88
        snapshot=log.read()
        snapshot[0]['data']['revision']=77
        assert log.read()[0]['data']['revision']==1
    assert log.read()[0]['data']['revision']==1
