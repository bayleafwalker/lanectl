from pathlib import Path
import json
import re
import shutil
import subprocess
from lanectl import cli, runner, specification as s
from lanectl.events import open_log, project_items

root = Path('/projects/dev/lanectl')
scratch = Path('/tmp/hla-onboarding-native-spec-review-r3-20261115')
packet = root / 'docs/evidence/2026-11-15-product-contact/onboarding-planner-lint-r2'
release = root / 'backlog/hla-onboarding-expand'
draft = scratch / 'qualified-draft'
state_path = scratch / 'guarded-run-state.json'
log = open_log()
item = 'hla-onboarding-expand'
prior = 'hla-onboarding-expand-a1'
state = {'phase': 'preflight', 'prior_attempt': prior, 'total_outcome_limit': 2}
def save(**values):
    state.update(values)
    state_path.write_text(json.dumps(state, indent=2) + '\n')
def command(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True)
def one_remaining(attempts):
    assert len(attempts) == 1 and attempts[0]['attempt_id'] == prior, 'outcome retry budget changed'
view = project_items(log.read())[item]
one_remaining(view.attempts)
assert view.state == 'parked' and view.release_revision == 1
try:
    one_remaining([*view.attempts, {'attempt_id': 'negative-control-extra-attempt'}])
except AssertionError:
    save(aggregate_budget_negative_control='rejected extra attempt')
else:
    raise AssertionError('retry budget guard did not reject an extra attempt')
assert s.validate_for_publish(draft) == []
assert json.loads((draft / 'specification.json').read_text())['review']['verdict'] == 'accept'
assert command('git','-C',str(root),'branch','--show-current').stdout.strip() == 'main'
command('git','-C',str(root),'diff','--exit-code')
command('git','-C',str(root),'diff','--cached','--exit-code')
timer = subprocess.run(['systemctl','--user','is-active','lanectl-tick.timer'], text=True, capture_output=True).stdout.strip()
assert timer in ('active','inactive'), 'unrecognized tick timer state'
claim = None
published = False
save(timer_initial=timer)
if timer == 'active':
    command('systemctl','--user','stop','lanectl-tick.timer')
try:
    assert command('systemctl','--user','show','lanectl-tick.timer','--property=ActiveState','--value').stdout.strip() == 'inactive', 'tick timer not quiescent'
    assert command('systemctl','--user','show','lanectl-tick.service','--property=ActiveState','--value').stdout.strip() == 'inactive', 'tick service not quiescent; do not race admission'
    save(phase='guarded-publication', timer_held=True)
    # The draft bit is written first: no partial new packet can be admitted.
    shutil.copy2(draft / 'release.toml', release / 'release.toml')
    shutil.copy2(draft / 'files/tests/test_onboarding_expand_acceptance.py', release / 'files/tests/test_onboarding_expand_acceptance.py')
    shutil.copy2(draft / 'specification.json', release / 'specification.json')
    assert s.validate_for_publish(release) == []
    actual = s.run_tests_at
    def recorded(*args, **kwargs):
        code, output = actual(*args, **kwargs)
        (scratch / 'publication-base-lint.log').write_text(output)
        failed = set(re.findall(r'^FAILED tests/test_onboarding_expand_acceptance.py::test_onboarding\[([^]]+)\]', output, re.M))
        expected = {'expand_core','expand_then_minimise','expand_source_transition','dismiss_after_override','storage_failure'}
        proof = {'returncode': code, 'failed_cases': sorted(failed), 'actual_population_qualified': code == 1 and failed == expected and '5 failed, 11 passed' in output and not re.search(r'\b\d+ (?:errors?|skipped)\b', output)}
        (scratch / 'publication-base-population.json').write_text(json.dumps(proof, indent=2) + '\n')
        assert proof['actual_population_qualified'], 'publication base population is invalid'
        return code, output
    s.run_tests_at = recorded
    try:
        assert cli.main(['backlog','publish',item]) == 0
    finally:
        s.run_tests_at = actual
    published = True
    publication = packet / 'publication'
    publication.mkdir(exist_ok=False)
    for name in ['publication-base-lint.log','publication-base-population.json','bound-draft.json']:
        shutil.copy2(scratch / name, publication / name)
    shutil.copy2(__file__, publication / 'publish-and-run.py')
    for name in ['bind-reviewed-draft.py','guard-falsifiers.py','guard-falsifiers.json']:
        shutil.copy2(Path(__file__).parent / name, publication / name)
    command('git','-C',str(root),'add',str(release),str(packet / 'native-review'),str(publication))
    commit = command('git','-C',str(root),'commit','-m','backlog: publish reviewed onboarding planner correction without resetting history')
    print(commit.stdout, flush=True)
    pushed = command('git','-C',str(root),'push','origin','main')
    print(pushed.stderr, flush=True)
    save(phase='published', release_revision=2, release_digest=s.release_digest(release))
    one_remaining(project_items(log.read())[item].attempts)
    claim = runner.admit('implement', log, only=item)
    assert isinstance(claim, runner.Claim), claim
    assert claim.attempt_id == 'hla-onboarding-expand-a2' and claim.rel.revision == 2
    save(phase='native-attempt', attempt_id=claim.attempt_id, model=claim.model)
    print(f'claimed {claim.attempt_id} -> {claim.model}', flush=True)
    result = runner.execute(claim, log)
    save(phase='attempt-returned', result=result)
    print(result, flush=True)
finally:
    current = project_items(log.read())[item]
    # Inspect authoritative eligibility even if interrupted between publication
    # and the local published flag. Never restore scheduling for an eligible retry.
    if current.state in ('ready','requeued','rejected'):
        aid = current.attempts[-1]['attempt_id']
        print(runner.integrator_reject(log, aid, 'Coordinator preserves total two-attempt outcome limit across R1/R2. No further automatic attempt; failed history retained.', park=True), flush=True)
        current = project_items(log.read())[item]
    safe = current.state not in ('claimed','ready','requeued','rejected')
    if timer == 'active' and safe:
        command('systemctl','--user','start','lanectl-tick.timer')
    save(final_item_state=current.state, attempts_retained=len(current.attempts), timer_restored=(timer != 'active' or safe), needs_runner_recovery=not safe)
