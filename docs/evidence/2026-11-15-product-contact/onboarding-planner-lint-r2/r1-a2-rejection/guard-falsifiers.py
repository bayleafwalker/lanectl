"""Execute the actual workflow predicates/finalizer with effect-free stand-ins."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace as N

root = Path('/tmp/hla-onboarding-planner-lint-20261115')
tree = ast.parse((root / 'publish-and-run.py').read_text())
outer = next(n for n in reversed(tree.body) if isinstance(n, ast.Try) and n.finalbody)
def execute(nodes, env):
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'actual-workflow-fragment', 'exec'), env)
results = {}
for service in ['inactive','active','activating','deactivating','failed','unknown']:
    def command(*args):
        return N(stdout=('inactive' if 'lanectl-tick.timer' in args else service) + '\n')
    try:
        execute(outer.body[:2], {'command': command})
        accepted = True
    except AssertionError:
        accepted = False
    assert accepted == (service == 'inactive')
    results['service_' + service] = 'accepted' if accepted else 'rejected'

for parking_fails in (False, True):
    view = N(state='ready', attempts=[{'attempt_id': 'hla-onboarding-expand-a1'}])
    effects = []
    def park(*args, **kwargs):
        effects.append('park')
        if parking_fails:
            raise RuntimeError('injected parking failure')
        view.state = 'parked'
        return 'parked'
    env = dict(project_items=lambda events: {'hla-onboarding-expand': view},
               log=N(read=lambda: []), item='hla-onboarding-expand', published=False,
               runner=N(integrator_reject=park), timer='active',
               command=lambda *args: effects.append('restore-timer'),
               save=lambda **kwargs: effects.append(('save', kwargs)), print=lambda *args, **kwargs: None)
    try:
        execute(outer.finalbody, env)
    except RuntimeError:
        assert parking_fails
    if parking_fails:
        assert effects == ['park'], effects
        results['parking_failure'] = 'timer remains held'
    else:
        assert effects[0:2] == ['park','restore-timer'], effects
        assert view.state == 'parked' and len(view.attempts) == 1
        results['interrupted_after_publication_with_false_local_flag'] = 'authoritative ready state parked before timer restoration'

binding = ast.parse((root / 'bind-reviewed-draft.py').read_text())
asserts = [n for n in binding.body if isinstance(n, ast.Assert) and
           ('rel.outcome' in ast.unparse(n) or 'rel.base_sha' in ast.unparse(n))]
assert len(asserts) == 2
for outcome, base in [('reviewed outcome','reviewed base'),('changed outcome','reviewed base'),('reviewed outcome','changed base')]:
    try:
        execute(asserts, {'rel': N(outcome=outcome, base_sha=base),
                         'request': {'proposal': {'outcome': 'reviewed outcome'}, 'base_sha': 'reviewed base'}})
        accepted = True
    except AssertionError:
        accepted = False
    assert accepted == (outcome == 'reviewed outcome' and base == 'reviewed base')
    results['binding_' + outcome + '_' + base] = 'accepted' if accepted else 'rejected'

fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'one_remaining')
env = {'prior': 'hla-onboarding-expand-a1'}
execute([fn], env)
env['one_remaining']([{'attempt_id': env['prior']}])
try:
    env['one_remaining']([{'attempt_id': env['prior']}, {'attempt_id': 'extra-attempt'}])
except AssertionError:
    results['extra_attempt'] = 'rejected'
else:
    raise AssertionError('extra attempt admitted')
(root / 'guard-falsifiers.json').write_text(json.dumps(results, indent=2) + '\n')
print(json.dumps(results, indent=2))
