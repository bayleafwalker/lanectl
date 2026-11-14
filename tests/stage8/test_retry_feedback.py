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
