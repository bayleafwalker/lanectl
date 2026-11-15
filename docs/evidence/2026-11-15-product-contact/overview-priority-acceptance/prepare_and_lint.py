from datetime import datetime, timezone
from pathlib import Path
import hashlib
import importlib.metadata
import json
import os
import re
import subprocess
import time
from unittest.mock import patch

from lanectl import specification as spec
from lanectl.config import load_lane, load_release, load_repos

out = Path(__file__).resolve().parent
os.environ['LANECTL_HOME'] = '/projects/dev/lanectl'
os.environ['XDG_RUNTIME_DIR'] = '/run/user/1000'
os.environ['DBUS_SESSION_BUS_ADDRESS'] = 'unix:path=/run/user/1000/bus'
assert importlib.metadata.version('lanectl') == '0.2.14'
request = json.loads((out / 'request.json').read_text())
repo = load_repos()['homelab-analytics']
lane = load_lane('implement')
base = request['base_sha']
for ref in ['main', 'origin/main']:
    assert subprocess.check_output(['git', '-C', str(repo.path), 'rev-parse', ref], text=True).strip() == base
proposal = spec._proposal(json.loads((out / 'proposal.json').read_text()), repo, base)
test = proposal['tests']['tests/test_overview_priority_gate.py'].encode()
assert hashlib.sha256(test).hexdigest() == '659bc7989349a24c24d0d4b508ec2fb0cf9a108dc8b72205914f6ac0251f0062'
assert lane.max_attempts == 2 and lane.size_budget_lines['M'] == 700
draft = out / 'qualified-draft'
draft.mkdir()
release = spec._toml('hla-overview-priority', repo, base, request['title'], request['scope'],
                     'product-ui', 'M', 'public', proposal, 'gpt-6.1-terra',
                     'opencode-go/deepseek-v4-pro', 'implement', 'homelab-analytics#2908', True)
release = '\n'.join('exec = ' + json.dumps(request['acceptance_exec'])
                    if line.startswith('exec = ') else line for line in release.splitlines()) + '\n'
(draft / 'release.toml').write_text(release)
target = draft / 'files/tests/test_overview_priority_gate.py'
target.parent.mkdir(parents=True)
target.write_bytes(test)
load_release(draft)
assert spec.validate_for_publish(draft), 'unreviewed draft was publishable'
binding = {'base_sha': base, 'release_digest': spec.release_digest(draft),
           'test_sha256': hashlib.sha256(test).hexdigest(),
           'outcome_sha256': hashlib.sha256(proposal['outcome'].encode()).hexdigest(),
           'proposal_sha256': hashlib.sha256((out / 'proposal.json').read_bytes()).hexdigest(),
           'author_model': 'gpt-6.1-terra', 'reviewer_model': 'opencode-go/deepseek-v4-pro',
           'candidate': 'UNOBSERVED', 'implementation_attempts': 0, 'publication': False}
(out / 'source-binding.json').write_text(json.dumps(binding, indent=2) + '\n')
state = {'phase': 'baseline-running', 'started_at': datetime.now(timezone.utc).isoformat(),
         'release_digest': binding['release_digest'], 'implementation_attempt': False}
(out / 'baseline-state.json').write_text(json.dumps(state, indent=2) + '\n')
actual = spec.run_tests_at

def observed(*args, **kwargs):
    # Observe the actual standard call; do not replace commands or return values.
    result = actual(*args, **kwargs)
    code, output = result
    (out / 'official-base-lint.log').write_text(output)
    locations = re.findall(r'HLA_ACCEPTANCE_EVIDENCE=(\S+)', output)
    records = []
    for location in dict.fromkeys(locations):
        path = Path(location)
        records.append({'root': str(path), 'exists': path.is_dir()})
    (out / 'official-base-call.json').write_text(json.dumps({
        'code': code, 'classification': spec.classify_failure(output),
        'command_template': args[3], 'setup_command': args[4],
        'selected_files': kwargs.get('selected_files'),
        'evidence_locations': records, 'release_digest': binding['release_digest'],
        'candidate': 'UNOBSERVED'}, indent=2) + '\n')
    return result

started = time.monotonic()
try:
    with patch.object(spec, 'run_tests_at', observed):
        problems = spec._base_lint(draft, repo, lane, 900)
    state.update(phase='terminal', lint_problems=problems, exit=bool(problems))
except Exception as error:
    state.update(phase='terminal', exit=1, failure=type(error).__name__, reason=str(error))
    raise
finally:
    state['elapsed_s'] = round(time.monotonic() - started, 3)
    (out / 'baseline-state.json').write_text(json.dumps(state, indent=2) + '\n')
    print(json.dumps(state), flush=True)
