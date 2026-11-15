from pathlib import Path
import argparse
import hashlib
import importlib.metadata
import json
import subprocess

from lanectl import specification as spec
from lanectl.config import load_lane, load_repos, load_release

parser = argparse.ArgumentParser()
parser.add_argument('--test-sha256', required=True)
parser.add_argument('--outcome-sha256', required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parent
source = Path('/tmp/hla-inline-upload-acceptance-r5-20261115')
base = 'b2d0fe393ac0971e906cce275e91f45e94422593'
assert importlib.metadata.version('lanectl') == '0.2.14'
test = (source / 'tests/test_hla1587_acceptance.py').read_bytes()
outcome = (source / 'outcome.md').read_bytes()
assert hashlib.sha256(test).hexdigest() == args.test_sha256
assert hashlib.sha256(outcome).hexdigest() == args.outcome_sha256
repo, lane = load_repos()['homelab-analytics'], load_lane('implement')
for ref in ['main', 'origin/main']:
    assert subprocess.check_output(['git', '-C', str(repo.path), 'rev-parse', ref], text=True).strip() == base
spec._models('gpt-6.1-terra', 'opencode-go/deepseek-v4-pro', lane, repo, 'public')
proposal = spec._proposal({'outcome': outcome.decode(), 'tests': {
    'tests/test_hla1587_acceptance.py': test.decode()}}, repo, base)
encoded = json.dumps(proposal).encode()
assert spec.MAX_RESPONSE_BYTES < len(encoded) <= spec.MAX_PROPOSAL_BYTES
scope = ['apps/web/frontend/app/sources/**',
         'apps/web/frontend/components/source-row-upload*',
         'apps/web/frontend/lib/source-row-upload*',
         'apps/web/frontend/unit/**', 'tests/**', 'docs/**']
draft = root / 'qualified-draft'
draft.mkdir()
release = spec._toml('hla-source-row-upload', repo, base,
    'Upload from a stale source row without leaving /sources', scope,
    'product-ui', 'M', 'public', proposal, 'gpt-6.1-terra',
    'opencode-go/deepseek-v4-pro', 'implement', 'homelab-analytics#1587', True)
release = '\n'.join('exec = ' + json.dumps([
    'uv run --no-sync python tests/test_hla1587_acceptance.py'])
    if line.startswith('exec = ') else line for line in release.splitlines()) + '\n'
(draft / 'release.toml').write_text(release)
target = draft / 'files/tests/test_hla1587_acceptance.py'
target.parent.mkdir(parents=True)
target.write_bytes(test)
load_release(draft)
assert spec.validate_for_publish(draft), 'Unreviewed draft unexpectedly publishable'
(root / 'proposal.json').write_bytes(encoded)
binding = dict(base_sha=base, test_sha256=args.test_sha256,
    outcome_sha256=args.outcome_sha256, proposal_bytes=len(encoded),
    proposal_sha256=hashlib.sha256(encoded).hexdigest(),
    release_digest=spec.release_digest(draft), author_model='gpt-6.1-terra',
    reviewer_model='opencode-go/deepseek-v4-pro', publication=False,
    candidate='UNOBSERVED')
(root / 'source-binding.json').write_text(json.dumps(binding, indent=2) + '\n')
print(json.dumps(binding), flush=True)
