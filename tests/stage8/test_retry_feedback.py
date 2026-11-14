import hashlib

from lanectl import runner
from tests.seed.test_end_to_end import SUB_TEST, estate, scripted
from tests.stage4.test_acc_evaluate_approved import good
from tests.stage8.test_runner_coordination import configure
from tests.stage8.test_work_sync_extra import _set_work


def event(kind, item, **data):
    return {'type': kind, 'item_id': item, 'data': data}


def claim(item, aid, revision=1, model='model-old'):
    return event('item.claimed', item, attempt_id=aid, release_revision=revision, model=model)


def rejection(item, aid, reason, by='integrator'):
    return event('decision.recorded', item, attempt_id=aid, decision='rejected', by=by, reasons=[reason])


def test_feedback_filters_orders_deduplicates_and_bounds():
    events = [claim('x', 'a1'), rejection('x', 'a1', 'old'),
              rejection('x', 'a1', 'old'), claim('x', 'a2', 2),
              rejection('x', 'a2', 'wrong revision'), claim('y', 'b1'),
              rejection('y', 'b1', 'wrong item'), rejection('x', 'a1', 'gate', by='gates'),
              claim('x', 'a3'), rejection('x', 'a3', 'z' * 10000),
              claim('x', 'current'), rejection('x', 'current', 'current'),
              claim('x', 'future'), rejection('x', 'future', 'future')]
    feedback = runner._retry_feedback(events, 'x', 1, 'current')
    encoded = str(feedback)
    assert 'old' in encoded and 'model-old' in encoded
    assert encoded.count("'old'") == 1
    assert all(s not in encoded for s in ('wrong revision', 'wrong item', 'gate', 'current', 'future'))
    assert len(encoded) < 5000
    assert runner._retry_feedback(events, 'x', 1, 'missing') == []


def test_retry_prompt_reaches_adapter_and_matches_owner_digest(estate, monkeypatch):
    _, release, log = estate
    release('retry-proof', SUB_TEST)
    _set_work('retry-proof', 'target#12', True)
    owner = configure(monkeypatch)
    first = runner.admit('implement', log)
    runner.execute(first, log, adapter_fn=scripted(good))
    runner.integrator_reject(log, first.attempt_id, 'BOM input loses its leading character')
    captured = []
    def adapter(**kwargs):
        captured.append(kwargs['prompt'])
        return scripted(good)(**kwargs)
    second = runner.admit('implement', log)
    assert next(e for e in log.read() if e['type'] == 'item.claimed' and
                e['data']['attempt_id'] == second.attempt_id)['data']['prompt_feedback_version'] == 1
    runner.execute(second, log, adapter_fn=adapter)
    assert 'BOM input loses its leading character' in captured[0]
    starts = [call[1] for call in owner.calls if call[0] == 'start']
    assert starts[-1][3] == 'sha256:' + hashlib.sha256(captured[0].encode()).hexdigest()


def test_feedback_retains_exact_last_three_including_parked():
    events = []
    for number in range(1, 5):
        aid = f'a{number}'
        events.append(claim('x', aid, model=f'model-{number}'))
        decision = rejection('x', aid, f'reason-{number}')
        if number == 3:
            decision['data']['decision'] = 'parked'
        events.append(decision)
    events.append(claim('x', 'current'))
    assert runner._retry_feedback(events, 'x', 1, 'current') == [
        {'attempt_id': f'a{number}', 'model': f'model-{number}', 'reason': f'reason-{number}'}
        for number in (2, 3, 4)
    ]


def test_rendered_retry_prompt_stable_after_unrelated_and_later_events(estate):
    _, release, log = estate
    release('stable-proof', SUB_TEST)
    current = runner.admit('implement', log)
    events = [claim('stable-proof', 'prior'),
              rejection('stable-proof', 'prior', 'prior observation'),
              claim('stable-proof', current.attempt_id)]
    def rendered(history):
        feedback = runner._retry_feedback(history, current.rel.id, current.rel.revision,
                                          current.attempt_id)
        return runner.render_prompt(current.rel, current.lane, current.repo, feedback=feedback)
    before = rendered(events)
    events.extend([claim('other', 'other-attempt'), rejection('other', 'other-attempt', 'unrelated'),
                   rejection('stable-proof', 'prior', 'late observation'),
                   claim('stable-proof', 'future'), rejection('stable-proof', 'future', 'future observation')])
    assert 'prior observation' in before
    assert rendered(events) == before


def test_default_prompt_bytes_match_pre_feedback_version():
    from types import SimpleNamespace as S
    rel = S(title='Title', outcome='Outcome', acceptance=S(exec=('verify',), files=('accept.py',)),
            scope_paths=('src/**',), constraints=('Constraint',), allow_deps=False, size='S',
            escalate_when=('Unknown',))
    lane = S(protected_paths=('secret/**',), size_budget_lines={'S': 100})
    prompt = runner.render_prompt(rel, lane)
    # SHA-256 generated from the 0.2.10 renderer at 67f0917 with these fixed inputs.
    assert hashlib.sha256(prompt.encode()).hexdigest() == '64e33d799ebbf7e47b3ba9232846e4f0e037a0e8928cf3c3d93e3ceaf41c0169'
    assert runner.render_prompt(rel, lane, feedback=[]) == prompt


def test_malformed_feedback_fails_closed():
    bad_events = [claim('x', [], 1),
                  rejection('x', [], 'bad'),
                  rejection('x', 'a1', None),
                  rejection('x', 'a1', 42),
                  rejection('x', 'a1', 'not a list')]
    # Override the helper's normal list wrapper for malformed reasons.
    bad_events[2]['data']['reasons'] = None
    bad_events[3]['data']['reasons'] = 42
    bad_events[4]['data']['reasons'] = 'not a list'
    for bad in bad_events:
        assert runner._retry_feedback([claim('x', 'a1'), bad, claim('x', 'current')],
                                      'x', 1, 'current') == []


def test_required_coordination_refusal_precedes_render(monkeypatch):
    from types import SimpleNamespace
    from lanectl import coordination
    calls = []
    monkeypatch.setattr(coordination, 'configured', lambda *_: calls.append('configured'))
    monkeypatch.setattr(runner, '_coordination_park', lambda c, log, exc: str(exc))
    wrapped = runner._coordinate_execution(lambda *a, **kw: calls.append('native'))
    result = wrapped(SimpleNamespace(repo=SimpleNamespace(name='target')),
                     SimpleNamespace(read=lambda: []),
                     require_coordination=True)
    assert calls == ['configured']
    assert 'not configured' in result


def test_legacy_claim_keeps_original_prompt_even_with_previous_rejection(estate, monkeypatch):
    import json
    _, release, log = estate
    release('legacy-proof', SUB_TEST)
    _set_work('legacy-proof', 'target#12', True)
    owner = configure(monkeypatch)
    first = runner.admit('implement', log)
    runner.execute(first, log, adapter_fn=scripted(good))
    runner.integrator_reject(log, first.attempt_id, 'old rejection')
    current = runner.admit('implement', log)
    lines = [json.loads(line) for line in log.path.read_text().splitlines()]
    for e in lines:
        if e['type'] == 'item.claimed' and e['data']['attempt_id'] == current.attempt_id:
            e['data'].pop('prompt_feedback_version', None)
    log.path.write_text(''.join(json.dumps(e) + '\n' for e in lines))
    seen = []
    def adapter(**kwargs):
        seen.append(kwargs['prompt'])
        return scripted(good)(**kwargs)
    runner.execute(current, log, adapter_fn=adapter)
    expected = runner.render_prompt(current.rel, current.lane, current.repo)
    assert seen == [expected]
    assert [call[1] for call in owner.calls if call[0] == 'start'][-1][3] == (
        'sha256:' + hashlib.sha256(expected.encode()).hexdigest())


def test_unwrapped_execute_defaults_to_rendered_prompt(estate, monkeypatch):
    _, release, log = estate
    release('unwrapped-proof', SUB_TEST)
    c = runner.admit('implement', log)
    seen = []
    def adapter(**kwargs):
        seen.append(kwargs['prompt'])
        return scripted(good)(**kwargs)
    runner.execute.__wrapped__(c, log, adapter_fn=adapter)
    assert seen == [runner.render_prompt(c.rel, c.lane, c.repo)]


def test_malformed_feedback_does_not_park_uncoordinated_execution(estate, monkeypatch):
    from types import SimpleNamespace
    from lanectl import coordination
    _, release, log = estate
    release('malformed-proof', SUB_TEST)
    c = runner.admit('implement', log)
    malformed = rejection(c.rel.id, 'prior', 'bad')
    malformed['data']['reasons'] = None
    current = claim(c.rel.id, c.attempt_id)
    current['data']['prompt_feedback_version'] = 1
    history = [claim(c.rel.id, 'prior'), malformed, current]
    monkeypatch.setattr(coordination, 'configured', lambda *_: None)
    monkeypatch.setattr(runner, '_coordination_park', lambda *args: (_ for _ in ()).throw(AssertionError('parked')))
    seen = []
    wrapped = runner._coordinate_execution(lambda *args, **kwargs: seen.append(kwargs['prompt']))
    wrapped(c, SimpleNamespace(read=lambda: history))
    assert seen == [runner.render_prompt(c.rel, c.lane, c.repo)]
