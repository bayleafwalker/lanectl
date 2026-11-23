"""The selected policy retains headless budget checks and closed autonomy."""
from pathlib import Path
from types import SimpleNamespace
import subprocess
import tomllib

from lanectl import integrator, landing
from lanectl.config import RepoSpec


def authority():
    root = Path(__file__).resolve().parents[2]
    return tomllib.loads((root / 'governance/integrator.toml').read_text())


def test_model_error_permission_keeps_budget_and_automatic_cycle_closed(monkeypatch, tmp_path):
    policy = authority()
    assert policy['revision'] == 2
    assert policy['fix_budget_lines'] == 30
    assert policy['autonomous_classes'] == []
    assert policy['allowed_fix_classes'] == ['spec-gap', 'gate-gap', 'model-error']
    event = {'type': 'integrator.fix', 'data': {
        'attempt_id': 'fixture-a3', 'commit': 'f' * 40, 'fix_class': 'model-error'}}
    assert landing.fix_budget([event], policy, {'f' * 40: 30}) == []
    assert landing.fix_budget([event], policy, {'f' * 40: 31})
    unlisted = dict(event, data=dict(event['data'], fix_class='unlisted'))
    assert landing.fix_budget([unlisted], policy, {'f' * 40: 1})
    effects = []
    monkeypatch.setattr(integrator, '_authority', lambda: policy)
    monkeypatch.setattr(integrator, '_cycle', lambda *a: effects.append(True) or ['effect admitted'])
    log = SimpleNamespace(path=tmp_path / 'events.jsonl')
    assert integrator.cycle(log) == []
    assert effects == []
    # The same cycle must reach the effect boundary if its class guard opens.
    monkeypatch.setattr(integrator, '_authority', lambda: dict(policy, autonomous_classes=['fixture']))
    assert integrator.cycle(log) == ['effect admitted']
    assert effects == [True]


def test_cumulative_model_error_repairs_cannot_each_spend_the_whole_budget(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()

    def git(*args):
        return subprocess.run(['git', '-C', str(root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    git('init', '-b', 'main')
    git('config', 'user.name', 'fixture')
    git('config', 'user.email', 'fixture@example.invalid')
    (root / 'base').write_text('base\n')
    git('add', 'base')
    git('commit', '-m', 'test: establish fixture base')
    base = git('rev-parse', 'HEAD')
    git('checkout', '-b', 'train/policy-fixture')
    repo = RepoSpec('fixture', root, 'main', '', '', tmp_path / 'worktrees')
    train = {'train_id': 'policy-fixture', 'base_sha': base}
    for index, lines in enumerate((16, 15), 1):
        path = root / f'correction-{index}'
        path.write_text('fixture\n' * lines)
        git('add', path.name)
        git('commit', '-m', f'fix(fixture-a3): [model-error] correction {index}')
        warnings = integrator._fix_warnings(repo, train, [], authority())
        if index == 1:
            assert warnings == []
        else:
            assert warnings and 'exceeds allowed class or size' in warnings[0]
