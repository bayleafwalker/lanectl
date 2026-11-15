from pathlib import Path
import json
import re
import hashlib
from lanectl import specification as s
from lanectl.config import load_repos, load_lane, load_release

r = Path('/tmp/hla-onboarding-native-spec-review-r3-20261115')
request = json.loads((r / 'request.json').read_text())
repo = load_repos()['homelab-analytics']
lane = load_lane('implement')
proposal = s._proposal(request['proposal'], repo, request['base_sha'])
dest = r / 'qualified-draft'
assert not dest.exists()
dest.mkdir()
scope = ['apps/web/frontend/components/onboarding-checklist.js',
         'apps/web/frontend/lib/onboarding-checklist-state.mjs',
         'apps/web/frontend/app/page.js', 'apps/web/frontend/unit/**', 'tests/**', 'docs/**']
mandatory = ['uv run --no-sync python tests/test_onboarding_expand_acceptance.py']
text = s._toml('hla-onboarding-expand', repo, request['base_sha'],
              'Keep completed-core onboarding Expand open for the mounted session',
              scope, 'product-ui', 'M', 'public', proposal, 'gpt-6',
              'opencode-go/deepseek-v4-pro', 'implement', 'homelab-analytics#2904', True)
text = '\n'.join('exec = ' + json.dumps(mandatory) if line.startswith('exec = ') else line
                 for line in text.splitlines()) + '\n'
text = text.replace('revision = 1\n', 'revision = 2\n', 1)
(dest / 'release.toml').write_text(text)
for name, source in proposal['tests'].items():
    p = dest / 'files' / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(source)
load_release(dest)
actual = s.run_tests_at
observed = {}


def recorded(*args, **kwargs):
    code, output = actual(*args, **kwargs)
    (r / 'official-base-lint.log').write_text(output)
    (r / 'official-base-lint-exit.json').write_text(json.dumps({'returncode': code}) + '\n')
    observed.update(code=code, output=output)
    return code, output


s.run_tests_at = recorded
problems = s._base_lint(dest, repo, lane, 900)
output = observed['output']
failed = set(re.findall(r'^FAILED tests/test_onboarding_expand_acceptance.py::test_onboarding\[([^]]+)\]', output, re.MULTILINE))
expected = {'expand_core', 'expand_then_minimise', 'expand_source_transition',
            'dismiss_after_override', 'storage_failure'}
qualified = (not problems and observed['code'] == 1 and failed == expected
             and re.search(r'\b5 failed, 11 passed\b', output) is not None
             and not re.search(r'\b\d+ (?:errors?|skipped)\b', output))
proof = {'problems': problems, 'returncode': observed['code'], 'failed_cases': sorted(failed),
         'expected_failed_cases': sorted(expected), 'passed': 11, 'failed': 5,
         'errors': 0 if qualified else 'not qualified', 'skipped': 0 if qualified else 'not qualified',
         'actual_population_qualified': bool(qualified), 'base_sha': request['base_sha'],
         'acceptance_sha256': hashlib.sha256(proposal['tests']['tests/test_onboarding_expand_acceptance.py'].encode()).hexdigest(),
         'release_digest': s.release_digest(dest), 'publication': False,
         'candidate_evidence': 'UNOBSERVED'}
(r / 'base-population-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
print(json.dumps(proof), flush=True)
assert qualified, 'Actual base population is not expected semantic 11PASS/5FAIL'
