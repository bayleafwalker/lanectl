"""Publish exact accepted UI packet, then run the normal bounded implementation lane."""
import hashlib
import json
import os
import subprocess
import tomllib
from pathlib import Path

from lanectl import specification
from lanectl.config import load_lane

root = Path('/projects/dev/lanectl')
packet = root / 'backlog/hla-attention-ui'
raw = tomllib.loads((packet / 'release.toml').read_text())
base = 'b2d0fe393ac0971e906cce275e91f45e94422593'
assert raw['id'] == 'hla-attention-ui' and raw['revision'] == 1
assert raw['draft'] is True and raw['base_sha'] == base
assert raw['size'] == 'M' and raw['data_class'] == 'public'
assert raw['scope']['paths'] == ['apps/web/frontend/**', 'tests/**', 'docs/**']
test = 'tests/test_attention_current_ui_acceptance.py'
assert raw['acceptance']['files'] == [test]
assert raw['acceptance']['exec'] == ['uv run --no-sync python tests/test_attention_current_ui_acceptance.py']
test_digest = '57c9e9eef945a90d133a7a0f2b29194b1d9df7cd6a0007c52a50672b1fc02bf5'
proposal_digest = 'f0b12356e5724c56a603b442bc77ca36ebec9d8e3f1c6ec398fe059abb321d5a'
assert hashlib.sha256((packet / 'files' / test).read_bytes()).hexdigest() == test_digest
proposal_path = root / 'docs/evidence/2026-11-14-product-contact/ui-acceptance-draft/proposal.json'
assert hashlib.sha256(proposal_path.read_bytes()).hexdigest() == proposal_digest
proposal = json.loads(proposal_path.read_text())
assert raw['outcome'] == proposal['outcome'] and proposal['tests'][test] == (packet / 'files' / test).read_text()
evidence = json.loads((packet / 'specification.json').read_text())
assert evidence['review']['verdict'] == 'accept' and evidence['lint_problems'] == []
assert evidence['release_digest'] == specification.release_digest(packet)
assert evidence['author_provenance']['proposal_sha256'] == proposal_digest
assert evidence['author_provenance']['main_input_sha256'] == test_digest
assert evidence['author_model'] == 'gpt-6.1-terra' and evidence['reviewer_model'] == 'opencode-go/deepseek-v4-pro'
assert specification.validate_for_publish(packet) == []
review_root = Path('/tmp/lanectl-hla-ui-spec-r1-review')
assert evidence['diagnostics_root'] == str(review_root)
assert json.loads((review_root / 'retention.json').read_text())['complete'] is True
status = json.loads((review_root / 'invocation/runtime/status.json').read_text())
assert status['outcome'] == 'done' and status['exit_code'] == 0
assert status['model'] == evidence['reviewer_model']
actual = json.loads((review_root / 'actual-return.json').read_text())
assert actual['response'] == evidence['review']
lane = load_lane('implement')
assert lane.max_attempts == 2 and lane.timeout_s == 2700 and lane.size_budget_lines['M'] == 700
hla = Path('/projects/dev/homelab-analytics')
subprocess.run(['git', '-C', str(hla), 'fetch', 'origin'], check=True)
heads = subprocess.check_output(['git', '-C', str(hla), 'rev-parse', 'HEAD', 'origin/main'], text=True).splitlines()
assert heads == [base, base], heads
contracts = root / 'docs/evidence/2026-11-14-product-contact/ui-stage-contracts'
freeze = json.loads((contracts / 'freeze-review.json').read_text())
for item in freeze['artifacts']:
    assert hashlib.sha256((contracts / item['path']).read_bytes()).hexdigest() == item['digest']
    assert item['digest'] in raw['outcome']
env = dict(os.environ, LANECTL_HOME=str(root), XDG_RUNTIME_DIR='/run/user/1000',
           DBUS_SESSION_BUS_ADDRESS='unix:path=/run/user/1000/bus', PYTHONUNBUFFERED='1')
env['PATH'] = ('/projects/dev/homelab-analytics/.tooling/node-v20.20.1-linux-x64/bin:'
               '/nix/store/71c91xjkcj07khl9imgmgji5wzrxwy65-gnumake-4.4.1/bin:' + env['PATH'])
cli = '/home/bayleaf/.local/bin/lanectl'
subprocess.run([cli, 'backlog', 'publish', raw['id']], cwd=root, env=env, check=True)
assert not tomllib.loads((packet / 'release.toml').read_text()).get('draft', False)
assert specification.validate_for_publish(packet) == []
paths = ['backlog/hla-attention-ui/release.toml', 'backlog/hla-attention-ui/specification.json']
subprocess.run(['git', 'add', '--', *paths], cwd=root, check=True)
staged = subprocess.check_output(['git', 'diff', '--cached', '--name-only'], cwd=root, text=True).splitlines()
assert staged and set(staged).issubset(paths), staged
subprocess.run(['git', 'diff', '--cached', '--check'], cwd=root, check=True)
subprocess.run(['git', 'commit', '-m', 'docs: publish independently reviewed full attention UI'], cwd=root, check=True)
subprocess.run(['git', 'push', 'origin', 'main'], cwd=root, check=True)
print('exact reviewed full UI published; starting normal bounded implementation', flush=True)
subprocess.run([cli, 'run', '--item', raw['id'], '--max', '2'], cwd=root, env=env, check=True)
