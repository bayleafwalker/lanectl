"""Fenced train: fake systemd lifecycle, receipt trust, staging and mutation."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from lanectl import doctor, fenced_train, runner
from lanectl.config import load_repos

FAKE = '''#!{python}
import hashlib, json, os, pathlib, sys
root = pathlib.Path(__file__).resolve().parents[1]
trains, results, captures = root / 'trains', root / 'results', root / 'captures'
mode = (root / 'mode').read_text().strip()
args = sys.argv[1:]
unit = args[-1]
tid = unit.split('@', 1)[1].rsplit('.', 1)[0]

def receipt(back=True):
    req = (trains / tid / '.lanectl-train' / 'request.json').read_bytes()
    captures.mkdir(exist_ok=True)
    (captures / (tid + '.json')).write_bytes(req)
    (results / (tid + '.json')).write_text(json.dumps({{
        'version': 1, 'train_id': tid,
        'request_sha256': 'sha256:' + hashlib.sha256(req).hexdigest(),
        'outcome': 'succeeded', 'service_result': 'success',
        'exit_code': 'exited', 'exit_status': '0', 'handed_back': back}}))

if args[0] == 'start':
    (root / 'started').write_text(unit)
    if mode in ('stuck', 'unstoppable'):
        (root / 'active').write_text('1')
    elif mode == 'mutate':
        path = trains / tid / 'repo' / 'calc.py'
        path.write_text(path.read_text() + '# changed\\n')
        receipt()
    elif mode == 'head':
        (trains / tid / 'repo' / '.git' / 'HEAD').write_text('0' * 40 + '\\n')
        receipt()
    elif mode == 'intree':
        (trains / tid / '.lanectl-train' / 'result.json').write_text(json.dumps({{
            'version': 1, 'train_id': tid, 'request_sha256': 'forged',
            'outcome': 'succeeded', 'service_result': 'success',
            'exit_code': 'exited', 'exit_status': '0', 'handed_back': True}}))
    elif mode == 'symlink':
        (results / (tid + '.json')).symlink_to(
            trains / tid / '.lanectl-train' / 'request.json')
    elif mode == 'greedy':
        receipt()
        os.chmod(results / (tid + '.json'), 0o666)
    elif mode == 'noback':
        receipt(back=False)
    elif mode != 'noreceipt':
        receipt()
elif args[0] == 'show':
    print('ActiveState=' + ('active' if (root / 'active').exists() else 'inactive'))
elif args[0] == 'stop':
    (root / 'stopped').write_text(unit)
    if mode != 'unstoppable':
        (root / 'active').unlink(missing_ok=True)
'''


@pytest.fixture
def fenced(tmp_path, monkeypatch):
    root = tmp_path / 'fence'
    for name in ('trains', 'results', 'bin', 'captures'):
        (root / name).mkdir(parents=True)
    (root / 'mode').write_text('ok')
    for name, body in (('systemctl', FAKE.format(python=sys.executable)),
                       ('journalctl', 'import sys\nprint("fenced journal", sys.argv[-1])\n')):
        tool = root / 'bin' / name
        tool.write_text(f'#!{sys.executable}\n{body}')
        tool.chmod(0o755)
    for name, value in (('TRAIN_ROOT', root / 'trains'), ('RESULT_ROOT', root / 'results'),
                        ('TRUSTED_UID', os.getuid()), ('POLL_S', 0.01),
                        ('WAIT_MARGIN_S', 0.0), ('RECEIPT_GRACE_S', 0.05),
                        ('STOP_WAIT_S', 0.2)):
        monkeypatch.setattr(fenced_train, name, value)
    monkeypatch.setenv('PATH', str(root / 'bin') + os.pathsep + os.environ.get('PATH', ''))
    return root


def git_repo(tmp_path):
    repo = tmp_path / 'source'
    repo.mkdir()
    (repo / 'calc.py').write_text('def add(a, b):\n    return a + b\n')
    subprocess.run(['git', 'init', '-q', '-b', 'main', repo], check=True)
    subprocess.run(['git', '-C', repo, 'add', '-A'], check=True)
    subprocess.run(['git', '-C', repo, '-c', 'user.name=t', '-c', 'user.email=t@t',
                    'commit', '-qm', 'base'], check=True)
    head = subprocess.run(['git', '-C', repo, 'rev-parse', 'HEAD'],
                          capture_output=True, text=True).stdout.strip()
    return repo, head


def policy(repo, setup=''):
    return SimpleNamespace(setup_cmd=setup, name='target', path=repo)


def test_success_runs_the_fixed_unit_and_reads_the_root_receipt(fenced, tmp_path):
    repo, _ = git_repo(tmp_path)
    marker = tmp_path / 'must-not-run'
    result = fenced_train.run_command(policy(repo, 'echo setup'), repo, 'touch ' + str(marker))
    assert result.returncode == 0 and result.stderr == '', result.stderr
    assert 'fenced journal' in result.stdout and not marker.exists()
    unit = (fenced / 'started').read_text()
    assert unit.startswith('lanectl-train@') and unit.endswith('.service')
    assert not list((fenced / 'trains').iterdir())
    request = json.loads(next((fenced / 'captures').iterdir()).read_bytes())
    assert request['version'] == 1 and request['cwd'] == 'repo' and request['env'] == {}
    assert request['argv'][0] == '/run/current-system/sw/bin/bash'
    assert request['argv'][2] == f'set -e\necho setup\ntouch {marker}'
    assert request['timeout_sec'] == 1800
    assert re.fullmatch('[0-9a-f]{32}', request['nonce'])


def test_handed_back_false_never_succeeds(fenced, tmp_path):
    repo, _ = git_repo(tmp_path)
    (fenced / 'mode').write_text('noback')
    result = fenced_train.run_command(policy(repo), repo, 'true')
    assert result.returncode != 0 and not list((fenced / 'trains').iterdir())


def test_timeout_stops_the_exact_instance_before_cleanup(fenced, tmp_path):
    repo, _ = git_repo(tmp_path)
    (fenced / 'mode').write_text('stuck')
    result = fenced_train.run_command(policy(repo), repo, 'true', timeout_s=1)
    assert result.returncode != 0 and 'timed out' in result.stderr and 'stopped' in result.stderr
    assert (fenced / 'stopped').read_text() == (fenced / 'started').read_text()
    assert not list((fenced / 'trains').iterdir())


def test_unprovable_stop_leaves_a_named_actionable_orphan(fenced, tmp_path):
    repo, _ = git_repo(tmp_path)
    (fenced / 'mode').write_text('unstoppable')
    result = fenced_train.run_command(policy(repo), repo, 'true', timeout_s=1)
    unit = (fenced / 'started').read_text()
    assert result.returncode != 0 and 'orphan' in result.stderr and unit in result.stderr
    assert list((fenced / 'trains').iterdir())


@pytest.mark.parametrize('mode,needle', [('mutate', 'tracked source'), ('head', 'HEAD')])
def test_checks_that_change_source_or_head_cannot_pass(fenced, tmp_path, mode, needle):
    repo, head = git_repo(tmp_path)
    (fenced / 'mode').write_text(mode)
    result = fenced_train.run_command(policy(repo), repo, 'true')
    assert result.returncode != 0 and needle in result.stderr
    assert not list((fenced / 'trains').iterdir())
    assert subprocess.run(['git', '-C', repo, 'rev-parse', 'HEAD'], capture_output=True,
                          text=True).stdout.strip() == head


@pytest.mark.parametrize('mode', ['intree', 'symlink', 'greedy', 'noreceipt'])
def test_untrusted_or_forged_results_fail_closed(fenced, tmp_path, mode):
    repo, _ = git_repo(tmp_path)
    (fenced / 'mode').write_text(mode)
    result = fenced_train.run_command(policy(repo), repo, 'true')
    assert result.returncode != 0 and 'receipt' in result.stderr
    assert not list((fenced / 'trains').iterdir())


def test_staging_is_self_contained_and_never_runs_hostile_git_config(fenced, tmp_path):
    repo, head = git_repo(tmp_path)
    marker = tmp_path / 'filter-ran'
    (repo / '.gitattributes').write_text('* filter=evil\n')
    subprocess.run(['git', '-C', repo, 'config', 'filter.evil.smudge',
                    f'sh -c "touch {marker}; cat"'], check=True)
    subprocess.run(['git', '-C', repo, 'add', '-A'], check=True)
    subprocess.run(['git', '-C', repo, '-c', 'user.name=t', '-c', 'user.email=t@t',
                    'commit', '-qm', 'hostile attributes'], check=True)
    head = subprocess.run(['git', '-C', repo, 'rev-parse', 'HEAD'], capture_output=True,
                          text=True).stdout.strip()
    train_dir = fenced / 'trains' / 'manual'
    train_dir.mkdir()
    commit, tracked, manifest = fenced_train._stage(repo, train_dir / 'repo')
    dest = train_dir / 'repo'
    assert commit == head and '.gitattributes' in tracked and manifest
    assert (dest / 'calc.py').read_text() == 'def add(a, b):\n    return a + b\n'
    assert (dest / '.git' / 'HEAD').read_text().strip() == head
    assert not (dest / '.git' / 'objects' / 'info' / 'alternates').exists()
    assert (dest / 'calc.py').stat().st_nlink == 1 and not marker.exists()


def test_doctor_reports_absent_service_and_keeps_environment_warning(estate, monkeypatch):
    root = Path(os.environ['LANECTL_HOME'])
    path = root / 'governance/repos.toml'
    path.write_text(path.read_text() + '\ntrain_isolation = "systemd"\n')
    repos = load_repos()
    assert repos['target'].train_isolation == 'systemd'
    monkeypatch.setattr(doctor.shutil, 'which', lambda name: '/bin/true')
    monkeypatch.setattr(doctor.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(
        a[0], 1, '', 'not found'))
    findings = doctor.check_train_service(repos)
    assert findings[0].level == doctor.ERROR and 'absent' in findings[0].detail
    monkeypatch.setattr(doctor.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(
        a[0], 0, 'unit', ''))
    assert doctor.check_train_service(repos)[0].level == doctor.OK
    (root / 'governance/vuoro.toml').write_text('[repos.other]\ncredential_name="runner"\n')
    path.write_text(path.read_text().replace('systemd', 'environment'))
    findings = doctor.check_train_isolation(root, load_repos())
    assert any(f.level == doctor.WARN and 'environment-only' in f.detail for f in findings)


def test_coordinated_admission_accepts_systemd_repos(estate, monkeypatch):
    from tests.stage8.test_runner_coordination import configure
    from tests.stage8.test_work_sync_extra import _set_work
    _, release, log = estate
    release('fenced-admit', 'def test_ok():\n    assert True\n')
    _set_work('fenced-admit', 'target#12', True)
    configure(monkeypatch)
    path = Path(os.environ['LANECTL_HOME']) / 'governance/repos.toml'
    path.write_text(path.read_text() + '\ntrain_isolation = "systemd"\n')
    claim = runner.admit('implement', log)
    assert not isinstance(claim, str), claim
    assert claim.repo.train_isolation == 'systemd'
