from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import tomllib
from unittest.mock import patch

from lanectl import cli, specification as spec
from lanectl.config import load_lane, load_release, load_repos
from lanectl.events import open_log, project_items

root = Path('/projects/dev/lanectl')
scratch = Path(__file__).resolve().parent
draft = scratch / 'qualified-draft'
item = 'hla-overview-priority'
work = 'homelab-analytics#2908'
destination = root / 'backlog' / item
packet = root / 'docs/evidence/2026-11-15-product-contact/overview-priority-acceptance'
binding = json.loads((scratch / 'source-binding.json').read_text())
reference = json.loads((scratch / 'official-base-proof.json').read_text())['cases']
os.environ['LANECTL_HOME'] = str(root)
os.environ['XDG_RUNTIME_DIR'] = '/run/user/1000'
os.environ['DBUS_SESSION_BUS_ADDRESS'] = 'unix:path=/run/user/1000/bus'
state = {'phase': 'preflight', 'item': item, 'work': work,
         'implementation_attempts': 0, 'candidate': 'UNOBSERVED'}

def save(**values):
    state.update(values)
    state['measured_at'] = datetime.now(timezone.utc).isoformat()
    (scratch / 'publication-state.json').write_text(json.dumps(state, indent=2) + '\n')

def command(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True)

def pristine(events, releases):
    assert not releases, 'release/work already exists; preserve history'
    assert not any(event.get('item_id') == item or event.get('data', {}).get('work') == work
                   for event in events), 'work/item has existing history; no reset'

def existing_releases():
    found = []
    for path in (root / 'backlog').glob('*/release.toml'):
        value = tomllib.loads(path.read_text())
        if value.get('id') == item or value.get('work') == work:
            found.append(str(path))
    return found

pristine([], [])
for events, releases in [([{'item_id': item, 'data': {}}], []),
                         ([], ['prior-work-release']),
                         ([{'item_id': 'other', 'data': {'work': work}}], [])]:
    try:
        pristine(events, releases)
    except AssertionError:
        pass
    else:
        raise AssertionError('history refusal failed')
log = open_log()
pristine(log.read(), existing_releases())
assert not destination.exists() and not packet.exists()
assert spec.validate_for_publish(draft) == []
assert spec.release_digest(draft) == binding['release_digest']
assert command('git', '-C', str(root), 'branch', '--show-current').stdout.strip() == 'main'
command('git', '-C', str(root), 'diff', '--exit-code')
command('git', '-C', str(root), 'diff', '--cached', '--exit-code')
assert command('git', '-C', str(root), 'rev-parse', 'HEAD').stdout == command('git', '-C', str(root), 'rev-parse', 'origin/main').stdout
repo, lane = load_repos()['homelab-analytics'], load_lane('implement')
assert lane.max_attempts == 2 and lane.size_budget_lines['M'] == 700
for ref in ['main', 'origin/main']:
    assert command('git', '-C', str(repo.path), 'rev-parse', ref).stdout.strip() == binding['base_sha']
timer = command('systemctl', '--user', 'is-active', 'lanectl-tick.timer').stdout.strip()
assert timer == 'active', 'preserve unexpected scheduler state for diagnosis'
save(phase='quiesce', forced_history_refusals=3, timer_initial=timer)
command('systemctl', '--user', 'stop', 'lanectl-tick.timer')
complete = False
try:
    deadline = time.monotonic() + 45
    while command('systemctl', '--user', 'show', 'lanectl-tick.service', '-pActiveState', '--value').stdout.strip() != 'inactive':
        assert time.monotonic() < deadline, 'existing tick is still active'
        time.sleep(0.2)
    pristine(log.read(), existing_releases())
    shutil.copytree(draft, destination)
    assert load_release(destination).draft
    actual = spec.run_tests_at

    def observed(*args, **kwargs):
        code, output = actual(*args, **kwargs)
        (scratch / 'publication-base-lint.log').write_text(output)
        roots = set(re.findall(r'HLA_ACCEPTANCE_EVIDENCE=(\S+)', output))
        assert len(roots) == 1, 'missing/ambiguous actual inner population'
        rows = json.loads((Path(next(iter(roots))) / 'result/classified-population.json').read_text())
        cases = {row['name']: row['classification'] for row in rows}
        assert len(rows) == len(cases) == 53 and cases == reference
        assert not any(row['error'] or row['skipped'] for row in rows)
        assert code == 1 and spec.classify_failure(output) == 'expected'
        (scratch / 'publication-base-proof.json').write_text(json.dumps({
            'release_digest': binding['release_digest'], 'code': code,
            'classification': 'expected', 'cases': cases, 'passed': 30, 'semantic': 23,
            'errors': 0, 'skipped': 0, 'unchanged_ordinary_command': args[3],
            'implementation_attempts': 0, 'candidate': 'UNOBSERVED'}, indent=2) + '\n')
        return code, output

    save(phase='guarded-publication')
    with patch.object(spec, 'run_tests_at', observed):
        assert cli.main(['backlog', 'publish', item]) == 0
    assert not load_release(destination).draft
    assert spec.release_digest(destination) == binding['release_digest']
    view = project_items(log.read())[item]
    assert view.state == 'ready' and not view.attempts
    save(phase='published-before-git', release_digest=binding['release_digest'])
    packet.mkdir(parents=True)
    names = ['outcome.md', 'request.json', 'proposal.json', 'final-author-proof.json',
             'source-binding.json', 'review-prompt.txt', 'review_native.py', 'review-process.json',
             'review.json', 'review-usage.json', 'native-stream.jsonl', 'native-result.json',
             'native-status.json', 'native-response.json', 'prepare_and_lint.py', 'finalize.py',
             'baseline-state.json', 'official-base-lint.log', 'official-base-call.json',
             'official-base-proof.json', 'publication-binding-negative-proof.json',
             'publish.py', 'publication-base-lint.log', 'publication-base-proof.json']
    for name in names:
        shutil.copyfile(scratch / name, packet / name)
    shutil.copyfile(scratch / 'publication-state.json', packet / 'publication-state-before-git.json')
    (packet / 'README.md').write_text(
        '# Independently qualified overview priority acceptance\n\n'
        'HLA2908 is a pre-existing publication/consumer priority correction on source '
        + binding['base_sha'] + '. The full named consumer scope remains intact. '
        'Original HLA1590/1593 outcomes and failed attempts are not completed, narrowed or reset.\n\n'
        'First-party Codex acceptance contains 53 cases. Ordinary CLI/pytest, real PostgreSQL, '
        'actual Next/Chromium and unavailable-native Docker fallback were qualified. '
        'Two root standard baseline runs each have 30 passing controls and 23 typed semantic '
        'failures, with zero errors/skips. The native Go Pro specification reviewer accepted '
        'after769.036s; this is static specification review, not candidate runtime evidence.\n\n'
        'Guarded publication binds the exact release, scope, outcome and gate bytes. '
        'Changed acceptance/release/review and existing item/work history were forced to refuse. '
        'The normal lane retains M700 including all candidate tests/docs/generated lines and '
        'two actual implementation attempts. Candidate green and implementation are unobserved '
        'at this checkpoint. Full Make/55 unchanged visuals, architecture, seven specialist reviews, '
        'product intention, train/dev, all PR CI and canonical adoption remain required.\n\n'
        'Docker is required for PostgreSQL; Linux x86_64 and pinned Node are explicit. Ordinary '
        'minimal-environment browser runs used Docker fallback; direct native proof used the '
        'same bound runner/test and qualified read-only browser libraries. No hosted CI claim. '
        'Prior harness failures and raw synthetic auth/runtime traces remain host-persistent '
        'under the referenced /tmp author directories; selected source-bound metadata is retained '
        'here. No credentials, runtime image layers or private hosted observations are included.\n\n'
        'This selected packet is cross-host-replicated after push. Served work state is '
        'durable-authoritative; /tmp artifacts remain host-local.\n')
    manifest = [{'path': str(path.relative_to(packet)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                for path in sorted(packet.rglob('*')) if path.is_file()]
    (packet / 'sha256.json').write_text(json.dumps({'schema': 'retained-files/v1', 'files': manifest}, indent=2) + '\n')
    command('gitleaks', 'dir', str(packet), '--no-banner', '--redact')
    command('gitleaks', 'dir', str(destination), '--no-banner', '--redact')
    command('git', '-C', str(root), 'add', str(destination), str(packet))
    result = command('git', '-C', str(root), 'commit', '-m', 'backlog: publish independently qualified overview priority correction')
    print(result.stdout, flush=True)
    result = command('git', '-C', str(root), 'push', 'origin', 'main')
    print(result.stderr, flush=True)
    complete = True
    save(phase='published-durable', canonical_commit=command('git', '-C', str(root), 'rev-parse', 'HEAD').stdout.strip())
finally:
    if not complete:
        view = project_items(log.read()).get(item)
        if view is not None and view.state in ('ready', 'requeued', 'rejected') and not view.attempts:
            log.append('item.parked', {'reason': 'Publication interrupted before durable canonical push; zero implementation attempts retained.'}, item_id=item)
    command('systemctl', '--user', 'start', 'lanectl-tick.timer')
    save(timer_restored=True)
print(json.dumps(state), flush=True)
