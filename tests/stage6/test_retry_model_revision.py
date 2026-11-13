"""Retry routing considers the current release and avoids consecutive models."""
from dataclasses import replace

from lanectl import runner
from lanectl.contracts import Acceptance, LaneRevision, WorkRelease
from lanectl.events import ItemView


def release(**overrides):
    values = dict(id='item-1', repo='target', base_sha='a' * 40, title='t', outcome='o',
                  task_class='glue', size='S', data_class='public', scope_paths=('src/**',),
                  acceptance=Acceptance(exec=('true',)), revision=2)
    values.update(overrides)
    return WorkRelease(**values)


def lane(routing, retry='different_model', external_models=()):
    return LaneRevision(lane='implement', revision=1, size_max='M', routing=routing,
                        max_attempts=4, retry=retry, caps={}, size_budget_lines={'S': 100},
                        protected_paths=(), dependency_manifests=(), test_globs=(),
                        forbidden_added_patterns=(), external_models=external_models)


def view(*attempts):
    return ItemView('item-1', attempts=list(attempts))


def attempt(model, revision=2, **extra):
    return dict(model=model, release_revision=revision, **extra)


def test_current_revision_preferred_and_exhaustion_avoids_immediate_repeat():
    policy = lane({'flash': 1, 'pro': 3})
    history = view(attempt('pro', 1), attempt('flash'))
    assert runner.candidate_weights(release(), policy, history) == {'pro': 3}
    history.attempts.append(attempt('pro'))
    history.attempts.append(attempt('flash'))
    assert runner.candidate_weights(release(), policy, history) == {'pro': 3}
    assert runner.pick_model(release(), policy, history) == 'pro'


def test_three_models_preserve_weights_and_deterministic_choice():
    policy = lane({'a': 1, 'b': 2, 'c': 4})
    history = view(attempt('a'))
    assert runner.candidate_weights(release(), policy, history) == {'b': 2, 'c': 4}
    assert runner.pick_model(release(), policy, history) == 'c'  # weighted hash for item-1:1
    history.attempts.extend([attempt('b'), attempt('c')])
    assert runner.candidate_weights(release(), policy, history) == {'a': 1, 'b': 2}


def test_single_positive_and_empty_routes():
    history = view(attempt('a'))
    assert runner.candidate_weights(release(), lane({'a': 1, 'zero': 0, 'negative': -1}), history) == {'a': 1}
    assert runner.candidate_weights(release(), lane({'zero': 0, 'negative': -1}), history) == {}
    assert runner.pick_model(release(), lane({}), history) is None


def test_ineligible_and_author_models_are_never_restored(tmp_path):
    (tmp_path / 'release.toml').write_text('[specification]\nauthor_model = "author"\n')
    rel = release(release_dir=str(tmp_path))
    policy = lane({'author': 4, 'pro': 2, 'zero': 0}, external_models=('external',))
    history = view(attempt('author'), attempt('pro'), attempt('removed'))
    assert runner.candidate_weights(rel, policy, history) == {'pro': 2}
    policy = lane({'author': 4, 'pro': 2, 'flash': 1, 'zero': 0})
    history = view(attempt('pro'), attempt('flash'), attempt('removed'))
    assert runner.candidate_weights(rel, policy, history) == {'pro': 2, 'flash': 1}
    restricted = replace(rel, data_class='restricted')
    policy = lane({'claude-pro': 2, 'external': 1}, external_models=('external',))
    assert runner.candidate_weights(restricted, policy, view(attempt('claude-pro'), attempt('external'))) == {'claude-pro': 2}


def test_legacy_missing_revision_and_infra_remain_retry_history():
    policy = lane({'a': 1, 'b': 1, 'c': 1})
    history = view({'model': 'a'}, attempt('b', infra=True))
    assert runner.candidate_weights(release(), policy, history) == {'c': 1}
    assert runner.attempts_used(history, 2) == 0


def test_other_retry_policy_is_unchanged():
    policy = lane({'a': 1, 'b': 2, 'zero': 0}, retry='same_model')
    assert runner.candidate_weights(release(), policy, view(attempt('a'))) == {'a': 1, 'b': 2}
