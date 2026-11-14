"""Start the normal bounded lane only after exact reviewed publication."""
import hashlib
import json
import os
import subprocess
import tomllib
from pathlib import Path

from lanectl import specification

root = Path('/projects/dev/lanectl')
packet = root / 'backlog/hla-attention-records-r5'
raw = tomllib.loads((packet / 'release.toml').read_text())
assert raw['revision'] == 4
assert raw['base_sha'] == '30c0caf6c78d257ff5db79f42cca0b56a0f934b9'
frozen = packet / 'files/tests/test_attention_record_api.py'
assert hashlib.sha256(frozen.read_bytes()).hexdigest() == '34da78c8cb79c5ecc6d38e740c6b2ee90433dc000e6633cb3bf853aff6bb3abb'
evidence = json.loads((packet / 'specification.json').read_text())
assert evidence['review']['verdict'] == 'accept'
assert evidence['lint_problems'] == []
assert specification.validate_for_publish(packet) == []
assert raw['draft'] is True
assert raw['acceptance']['files'] == ['tests/test_attention_record_api.py', 'tests/test_attention_record_pg_gate.py']
assert hashlib.sha256((packet / 'files/tests/test_attention_record_pg_gate.py').read_bytes()).hexdigest() == '7cc1222151c01559ef58b9ff473f73a13d0b99800ac111ca5674930e25098aad'
assert raw['acceptance']['exec'] == [
    "uv run --no-sync python -m pytest -q -p no:cacheprovider tests/test_attention_record_api.py",
    "uv run --no-sync python -m pytest -q -p no:cacheprovider -m 'integration and slow' tests/test_attention_record_api.py",
    "uv run --no-sync python tests/test_attention_record_pg_gate.py",
]
assert evidence['scope_revision']['proposal_sha256'] == 'd436cb23e893b6667b81aeea1c8549b1489017a83b20f746e8fb1c7335cf4093'
assert evidence['diagnostics_root'] == '/tmp/lanectl-hla-api-r4-review-r3'
review_root = Path(evidence['diagnostics_root'])
status = json.loads((review_root / 'invocation/runtime/status.json').read_text())
assert status['outcome'] == 'done' and status['exit_code'] == 0
assert json.loads((review_root / 'retention.json').read_text())['complete'] is True
assert status['model'] == 'opencode-go/deepseek-v4-pro'
from lanectl.config import load_lane
lane = load_lane('implement')
assert lane.max_attempts == 2 and lane.timeout_s == 2700
assert lane.size_budget_lines['M'] == 700
assert 'integration and slow' in raw['acceptance']['exec'][1]
hla = '/projects/dev/homelab-analytics'
subprocess.run(['git', '-C', hla, 'fetch', 'origin'], check=True)
observed_heads = subprocess.check_output(
    ['git', '-C', hla, 'rev-parse', 'HEAD', 'origin/main'], text=True).splitlines()
canonical_head = '529e41807dc3a6d22fe42bb61594be8a7fbe1f1b'
assert observed_heads[1] == canonical_head, observed_heads
assert observed_heads[0] in (raw['base_sha'], canonical_head), observed_heads
subprocess.run(['git', '-C', hla, 'merge-base', '--is-ancestor', raw['base_sha'], canonical_head], check=True)
allowed_doc_delta = {
    'docs/README.md',
    'docs/plans/2026-11-14-basis-tracked-revalidation.md',
    'docs/plans/household-outcome-evidence-decision-plan.md',
    'requirements/analytics-and-reporting.md',
}
delta = subprocess.check_output(['git', '-C', hla, 'diff', '--name-only', raw['base_sha'], canonical_head], text=True).splitlines()
assert set(delta) == allowed_doc_delta, delta
# Exact docs-only advance independently reviewed against product intention.
# Keep the reviewed release base, and integrate candidate with current main in the normal train.
if observed_heads[0] != canonical_head:
    subprocess.run(['git', '-C', hla, 'merge', '--ff-only', 'origin/main'], check=True)
assert subprocess.check_output(['git', '-C', hla, 'rev-parse', 'HEAD'], text=True).strip() == canonical_head

env = dict(os.environ, LANECTL_HOME=str(root), XDG_RUNTIME_DIR='/run/user/1000',
           DBUS_SESSION_BUS_ADDRESS='unix:path=/run/user/1000/bus', PYTHONUNBUFFERED='1')
env['PATH'] = ('/projects/dev/homelab-analytics/.tooling/node-v20.20.1-linux-x64/bin:'
               '/nix/store/71c91xjkcj07khl9imgmgji5wzrxwy65-gnumake-4.4.1/bin:' + env['PATH'])
cli = '/home/bayleaf/.local/bin/lanectl'

# Publication repeats the real expected-base-failure check. No event injection.
subprocess.run([cli, 'backlog', 'publish', raw['id']], cwd=root, env=env, check=True)
assert not tomllib.loads((packet / 'release.toml').read_text()).get('draft', False)
assert specification.validate_for_publish(packet) == []
paths = ['backlog/hla-attention-records-r5/release.toml',
         'backlog/hla-attention-records-r5/specification.json',
         'backlog/hla-attention-records-r5/files/tests/test_attention_record_api.py']
subprocess.run(['git', 'add', '--', *paths], cwd=root, check=True)
staged = subprocess.check_output(['git', 'diff', '--cached', '--name-only'], cwd=root, text=True).splitlines()
assert staged and set(staged).issubset(paths), staged
subprocess.run(['git', 'diff', '--cached', '--check'], cwd=root, check=True)
subprocess.run(['git', 'commit', '-m', 'docs: publish independently reviewed full attention API revision4'], cwd=root, check=True)
subprocess.run(['git', 'push', 'origin', 'main'], cwd=root, check=True)
print('exact reviewed full API packet published to canonical main; normal bounded lane starting', flush=True)
subprocess.run([cli, 'run', '--item', raw['id'], '--max', '2'], cwd=root, env=env, check=True)
