from dataclasses import replace

from lanectl import delivery_policy
from lanectl.config import load_lane
from lanectl.events import project_items
from lanectl.gates import decision, diffpolicy


def test_snapshot_roundtrip_and_prospective_diff():
    lane = replace(load_lane('implement'), delivery_policy='review-progress')
    binding = delivery_policy.snapshot(lane)
    assert delivery_policy.from_binding(binding) == lane
    rel = type('Release', (), dict(size='S', scope_paths=('src/**',), allow_deps=False,
                                   allow_test_edits=False))()
    changes = [diffpolicy.FileChange('A', 'src/a.py', added=100000)]
    assert not diffpolicy.evaluate(changes, rel, lane)
    assert decision.decide({'acceptance': ['failed']}, 'done', 99, 2,
                           policy_mode='review-progress')[::2] == ('rejected', 'park')


def test_revision_cannot_reopen_failure():
    events = [dict(item_id='x', type='release.published', data={'revision': 1}),
              dict(item_id='x', type='item.parked', data={'reason': 'failure'}),
              dict(item_id='x', type='release.published', data={'revision': 2, 'preserve_terminal': True})]
    assert project_items(events)['x'].state == 'parked'


def test_progress_review_requires_terminal_failure_and_substantive_fields(tmp_path):
    import pytest
    from lanectl import runner
    from lanectl.contracts import ContractError
    from lanectl.events import EventLog
    log = EventLog(tmp_path / 'events.jsonl')
    binding = delivery_policy.snapshot(replace(load_lane('implement'), delivery_policy='review-progress'))
    log.append('release.published', {'release_id': 'xx', 'revision': 1,
                                    'effective_policy': binding}, item_id='xx')
    log.append('item.claimed', {'attempt_id': 'xx-a1', 'lane': 'implement', 'model': 'm',
                                'worker': 'w', 'effective_policy': binding}, item_id='xx')
    log.append('decision.recorded', {'attempt_id': 'xx-a1', 'decision': 'rejected',
                                    'reasons': ['acceptance failed'], 'rules_revision': 'v1'}, item_id='xx')
    log.append('item.parked', {'reason': 'acceptance failed'}, item_id='xx')
    with pytest.raises(ContractError):
        runner.review_progress(log, 'xx-a1', 'continue', '', 'tests fail', 'repair needed')
    assert project_items(log.read())['xx'].state == 'parked'
    assert 'cannot be approved' in runner.approve(log, 'xx-a1', 'skip failure')
    runner.review_progress(log, 'xx-a1', 'continue', 'implemented parser', 'repair tests', 'viable next step')
    assert project_items(log.read())['xx'].state == 'requeued'


def test_bound_policy_does_not_restore_authority():
    import pytest
    lane = load_lane('implement')
    binding = delivery_policy.snapshot(lane)
    tightened = replace(lane, caps={**lane.caps, 'concurrency': 1},
                        protected_paths=lane.protected_paths + ('sensitive/**',),
                        timeout_s=1)
    effective = delivery_policy.effective_lane(binding, tightened)
    assert effective.caps['concurrency'] == 1
    assert 'sensitive/**' in effective.protected_paths
    rel = type('Release', (), dict(size='S', scope_paths=('src/**',), allow_deps=False,
                                   allow_test_edits=False))()
    old_protected = lane.protected_paths[0].replace('**', 'file')
    for path in (old_protected, 'sensitive/file'):
        assert diffpolicy.is_protected_violation(diffpolicy.evaluate(
            [diffpolicy.FileChange('A', path, added=1)], rel, effective))
    assert effective.size_budget_lines == lane.size_budget_lines
    assert effective.max_attempts == lane.max_attempts
    assert effective.timeout_s == 1
    with pytest.raises(ValueError, match='effect or sandbox'):
        delivery_policy.effective_lane(binding, replace(lane, effects={'push': 'none'}))
