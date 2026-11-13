from types import SimpleNamespace

from lanectl.events import EventLog
from lanectl.runner import sync_releases


def test_draft_sync_never_emits_publication(tmp_path):
    log = EventLog(tmp_path / 'events')
    sync_releases(log, [SimpleNamespace(id='sample-item', revision=1, draft=True)])
    assert log.read() == []


def test_observation_and_correction_preserve_attempt(tmp_path, monkeypatch):
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "proof").write_text("draft")
    subprocess.run(["git", "-C", str(repo), "add", "proof"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "proof"], check=True)
    sha = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    monkeypatch.setenv("LANECTL_HOME", str(repo))
    from lanectl.events import project_items
    from lanectl.publication import fingerprint, publication_evidence
    log = EventLog(tmp_path / 'events')
    old = log.append('release.published', {'release_id': 'sample-item', 'revision': 2}, item_id='sample-item')
    log.append('item.claimed', {'attempt_id': 'a1', 'lane': 'implement', 'model': 'm', 'worker': 'w'}, item_id='sample-item')
    log.append('release.publication.invalidated', {'release_id': 'sample-item', 'revision': 2,
        'target_event_sha256': fingerprint(old), 'reason': 'draft', 'evidence_ref': f'git:{sha}:proof'}, item_id='sample-item')
    sync_releases(log, [SimpleNamespace(id='sample-item', revision=2, draft=False)])
    sync_releases(log, [SimpleNamespace(id='sample-item', revision=2, draft=False)])
    events = log.read()
    assert [e['data']['provenance'] for _, e in publication_evidence(events)] == ['nondraft-observation']
    assert project_items(events)['sample-item'].state == 'claimed'
    assert len(project_items(events)['sample-item'].attempts) == 1


def test_invalid_target_fails(tmp_path):
    import pytest
    log = EventLog(tmp_path / 'events')
    with pytest.raises(ValueError, match='preceding matching'):
        log.append('release.publication.invalidated', {'release_id': 'sample-item', 'revision': 2,
            'target_event_sha256': 'a' * 64, 'reason': 'draft', 'evidence_ref': 'git:' + 'a' * 40 + ':proof'}, item_id='sample-item')


def test_duplicate_fingerprint_invalidation_and_bad_reference(tmp_path, monkeypatch):
    import subprocess
    import pytest
    from lanectl.contracts import make_event
    from lanectl.publication import fingerprint, publication_evidence, validate_invalidation
    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    (repo / 'proof').write_text('evidence')
    (repo / 'link').symlink_to('proof')
    subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Test', '-c', 'user.email=t@example.com', 'commit', '-qm', 'proof'], check=True)
    sha = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    monkeypatch.setenv('LANECTL_HOME', str(repo))
    original = make_event('release.published', {'release_id': 'sample-item', 'revision': 1}, item_id='sample-item')
    data = {'release_id': 'sample-item', 'revision': 1, 'target_event_sha256': fingerprint(original),
            'reason': 'draft', 'evidence_ref': f'git:{sha}:proof'}
    invalidation = make_event('release.publication.invalidated', data, item_id='sample-item')
    validate_invalidation(invalidation, [original, original])
    assert publication_evidence([original, original, invalidation]) == []
    for ref in ('permission', f'git:{sha}:link', f'git:{sha}:../proof', f'git:{sha}:missing'):
        invalidation['data'] = {**data, 'evidence_ref': ref}
        with pytest.raises(ValueError):
            validate_invalidation(invalidation, [original])


def test_queue_requires_earlier_guarded_receipt():
    from lanectl.accounting import accounting_timeline
    from lanectl.contracts import make_event
    def event(kind, data, minute):
        return make_event(kind, data, item_id='sample-item', ts=f'2026-11-13T10:{minute:02d}:00Z')
    claim = event('item.claimed', {'attempt_id': 'a1', 'lane': 'implement', 'model': 'm', 'worker': 'w'}, 3)
    def pub(provenance):
        return event('release.published', {'release_id': 'sample-item', 'revision': 1, **provenance}, 1)
    def seconds(events):
        return accounting_timeline(events, {}, item_id='sample-item')['phases']['queued']['seconds']
    assert seconds([pub({'provenance': 'guarded-publish'}), claim]) == 120
    assert seconds([pub({'provenance': 'nondraft-observation'}), claim]) is None
    assert seconds([pub({}), claim]) is None
    assert seconds([claim, pub({'provenance': 'guarded-publish'})]) is None


def test_guarded_publish_and_crash_reconciliation(tmp_path, monkeypatch):
    import pytest
    from lanectl import backlog, specification
    rel = SimpleNamespace(id='sample-item', revision=1, draft=True, release_dir=tmp_path,
                          outcome='Implement behavior', acceptance=SimpleNamespace(files=[]))
    path = tmp_path / 'release.toml'
    path.write_text('draft = true\n')
    monkeypatch.setattr(backlog, '_find', lambda _: rel)
    monkeypatch.setattr(specification, 'validate_for_publish', lambda _: [])
    monkeypatch.setattr(specification, 'publication_lint', lambda _: [])
    log = EventLog(tmp_path / 'events')
    args = SimpleNamespace(id=rel.id)
    assert backlog._publish(args, log) == 0
    assert log.read()[0]['data']['provenance'] == 'guarded-publish'
    rel.draft = False
    assert backlog._publish(args, log) == 0
    sync_releases(log, [rel])
    assert len(log.read()) == 1
    rel.draft = True
    path.write_text('draft = true\n')
    class Crash:
        def append(self, *args, **kwargs):
            raise RuntimeError('lost before receipt')
    with pytest.raises(RuntimeError):
        backlog._publish(args, Crash())
    assert 'draft = true' not in path.read_text()
    rel.draft = False
    fresh = EventLog(tmp_path / 'fresh-events')
    sync_releases(fresh, [rel])
    assert fresh.read()[0]['data']['provenance'] == 'nondraft-observation'


def test_failed_validation_never_publishes(tmp_path, monkeypatch):
    from lanectl import backlog, specification
    rel = SimpleNamespace(id='sample-item', revision=1, draft=True, release_dir=tmp_path,
                          outcome='Implement behavior', acceptance=SimpleNamespace(files=[]))
    (tmp_path / 'release.toml').write_text('draft = true\n')
    monkeypatch.setattr(backlog, '_find', lambda _: rel)
    monkeypatch.setattr(specification, 'validate_for_publish', lambda _: ['review rejected'])
    log = EventLog(tmp_path / 'events')
    assert backlog._publish(SimpleNamespace(id=rel.id), log) == 1
    assert log.read() == []
    assert 'draft = true' in (tmp_path / 'release.toml').read_text()


def test_lifecycle_facts_include_only_usable_matching_publications():
    from lanectl.contracts import make_event
    from lanectl.lifecycle import local_facts
    one = make_event('release.published', {'release_id': 'sample-item', 'revision': 1, 'provenance': 'guarded-publish'}, item_id='sample-item')
    other = make_event('release.published', {'release_id': 'other-item', 'revision': 1}, item_id='other-item')
    assert local_facts([one, other])['local.release']['value'] == [one, other]
    assert local_facts([one, other], item_id='sample-item')['local.release']['value'] == [one]


def test_resolver_rejects_invalid_history_context():
    import pytest
    from lanectl.contracts import make_event
    from lanectl.publication import fingerprint, publication_evidence
    one = make_event('release.published', {'release_id': 'sample-item', 'revision': 1}, item_id='sample-item')
    other = make_event('release.published', {'release_id': 'other-item', 'revision': 1}, item_id='other-item')
    data = {'release_id': 'sample-item', 'revision': 1, 'target_event_sha256': fingerprint(one),
            'reason': 'incorrect', 'evidence_ref': 'git:' + 'a' * 40 + ':proof'}
    invalid = make_event('release.publication.invalidated', data, item_id='sample-item')
    wrong_item = make_event('release.publication.invalidated', {**data, 'release_id': 'other-item'}, item_id='other-item')
    wrong_revision = make_event('release.publication.invalidated', {**data, 'revision': 2}, item_id='sample-item')
    missing = make_event('release.publication.invalidated', {**data, 'target_event_sha256': 'a' * 64}, item_id='sample-item')
    for history in ([one, wrong_item], [one, wrong_revision], [one, missing], [invalid, one]):
        with pytest.raises(ValueError, match='preceding matching'):
            publication_evidence(history)
    assert publication_evidence([one, one, other, invalid]) == [(3, other)]


def test_local_read_rejects_invalid_history_even_after_cursor(tmp_path):
    import json
    import pytest
    from lanectl.contracts import make_event
    from lanectl.publication import fingerprint
    log = EventLog(tmp_path / 'events')
    pub = make_event('release.published', {'release_id': 'sample-item', 'revision': 1}, item_id='sample-item')
    invalid = make_event('release.publication.invalidated', {'release_id': 'sample-item', 'revision': 2,
        'target_event_sha256': fingerprint(pub), 'reason': 'wrong revision', 'evidence_ref': 'git:' + 'a' * 40 + ':proof'}, item_id='sample-item')
    log.path.write_text('\n'.join(map(json.dumps, [pub, invalid])) + '\n')
    with pytest.raises(ValueError, match='preceding matching'):
        log.read(after=1)


def test_queue_uses_earliest_remaining_publication_before_first_claim():
    from lanectl.accounting import accounting_timeline
    from lanectl.contracts import make_event
    from lanectl.publication import fingerprint
    def pub(item, rev, provenance, minute):
        return make_event('release.published', {'release_id': item, 'revision': rev, **provenance}, item_id=item, ts=f'2026-11-13T10:{minute:02d}:00Z')
    def invalidate(event):
        d = event['data']
        return make_event('release.publication.invalidated', {'release_id': d['release_id'], 'revision': d['revision'],
            'target_event_sha256': fingerprint(event), 'reason': 'draft', 'evidence_ref': 'git:' + 'a' * 40 + ':proof'}, item_id=d['release_id'])
    claim = make_event('item.claimed', {'attempt_id': 'a1', 'lane': 'implement', 'model': 'm', 'worker': 'w'}, item_id='sample-item', ts='2026-11-13T10:03:00Z')
    guarded = pub('sample-item', 1, {'provenance': 'guarded-publish'}, 1)
    later = pub('sample-item', 2, {}, 4)
    other = pub('other-item', 1, {}, 0)
    legacy = pub('sample-item', 1, {}, 0)
    after_claim = pub('sample-item', 2, {'provenance': 'guarded-publish'}, 4)
    def seconds(events):
        return accounting_timeline(events, {}, item_id='sample-item')['phases']['queued']['seconds']
    assert seconds([guarded, claim, later, invalidate(later)]) == 120
    assert seconds([legacy, guarded, claim]) is None
    assert seconds([guarded, claim, invalidate(guarded), after_claim]) is None
    assert seconds([other, guarded, claim, invalidate(other)]) == 120


def test_pytest_loads_publication_modules_from_worktree():
    from pathlib import Path
    import lanectl
    import lanectl.lifecycle
    import lanectl.publication
    root = Path(__file__).resolve().parents[1] / 'src' / 'lanectl'
    for module in (lanectl, lanectl.lifecycle, lanectl.publication):
        actual = Path(module.__file__).resolve()
        print(f'PYTEST_IMPORT {module.__name__}={actual}')
        assert actual.parent == root


def test_reader_rejects_bad_ref_syntax_but_needs_no_git_objects(monkeypatch, tmp_path):
    import pytest
    from lanectl.contracts import make_event
    from lanectl.publication import fingerprint, publication_evidence
    pub = make_event('release.published', {'release_id': 'sample-item', 'revision': 1}, item_id='sample-item')
    invalid = make_event('release.publication.invalidated', {'release_id': 'sample-item', 'revision': 1,
        'target_event_sha256': fingerprint(pub), 'reason': 'draft', 'evidence_ref': 'git:' + 'a' * 40 + ':proof'}, item_id='sample-item')
    monkeypatch.setenv('LANECTL_HOME', str(tmp_path / 'no-repository'))
    assert publication_evidence([pub, invalid]) == []
    for ref in ('permission', 'git:' + 'a' * 40 + ':../proof', 'git:' + 'a' * 40 + ':dir//proof'):
        bad = {**invalid, 'data': {**invalid['data'], 'evidence_ref': ref}}
        with pytest.raises(ValueError, match='evidence_ref'):
            publication_evidence([pub, bad])
