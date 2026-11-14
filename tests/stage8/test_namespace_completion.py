"""Real manager stops must not manufacture a passing namespace train check."""
from dataclasses import replace
from pathlib import Path
import shlex
import subprocess
import threading
import time
import uuid

import pytest

from lanectl import runner, sandbox


def stop_during_check(monkeypatch, tmp_path, *, trap=False, prestart=False, ignore=False):
    """Stop only the unique unit after candidate code proves it started."""
    unit = f'lanectl-test-stop-{uuid.uuid4().hex}.service'
    ready, done = tmp_path / 'ready', tmp_path / 'done'
    original = sandbox.for_train
    monkeypatch.setattr(sandbox, 'for_train', lambda **kw: replace(
        original(**kw), unit=unit, timeout_s=30))
    if prestart:
        script = tmp_path / 'before-main.sh'
        script.write_text(f'touch {shlex.quote(str(ready))}; sleep 20\n')
        prefix = sandbox.Sandbox.prefix
        monkeypatch.setattr(sandbox.Sandbox, 'prefix', lambda self, cwd, env_path=None:
                            prefix(self, cwd, env_path) + ['-p', f'ExecStartPre=/bin/sh {script}'])
    command = (
        ('trap "" TERM; ' if ignore else 'trap "exit 0" TERM; ' if trap else '')
        + f'touch {shlex.quote(str(ready))}; sleep 45 & wait; touch {shlex.quote(str(done))}'
    )
    outcomes = []

    def stop():
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        if ready.exists():
            outcomes.append(subprocess.run(['systemctl', '--user', 'stop', unit],
                                           capture_output=True, timeout=20).returncode)

    thread = threading.Thread(target=stop)
    thread.start()
    return command, thread, outcomes, done


@pytest.mark.parametrize('trap,prestart', [(False, False), (True, False), (False, True)])
def test_stopped_namespace_command_is_failure(estate, monkeypatch, tmp_path, trap, prestart):
    spec = runner.load_repos()['target']
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    command, thread, stops, done = stop_during_check(
        monkeypatch, tmp_path, trap=trap, prestart=prestart)
    started = time.monotonic()
    try:
        result = runner._train_command(spec, checkout, command)
    finally:
        thread.join(25)
    assert not thread.is_alive()
    assert stops == [0]
    assert not done.exists()
    assert result.returncode != 0, result
    assert time.monotonic() - started < 10  # Stop, not the 30s start deadline.


def test_namespace_stop_kills_term_ignoring_child_within_bound(estate, monkeypatch, tmp_path):
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    command, thread, stops, done = stop_during_check(monkeypatch, tmp_path, ignore=True)
    started = time.monotonic()
    try:
        result = runner._train_command(runner.load_repos()['target'], checkout, command)
    finally:
        thread.join(25)
    assert not thread.is_alive()
    assert stops == [0]
    assert result.returncode != 0
    assert time.monotonic() - started < 25
    assert not done.exists()


@pytest.mark.parametrize('operation', ['build', 'recheck', 'historical'])
def test_stopped_check_never_becomes_checked_train(estate, monkeypatch, tmp_path, operation):
    from tests.stage8.test_work_sync_extra import _train, _head
    repo, release, log = estate
    release('stopped-check', 'def test_ok():\n    assert True\n')
    claim = runner.admit('implement', log)
    base = _head(repo)
    command, thread, stops, done = stop_during_check(monkeypatch, tmp_path, trap=True)
    original = runner.load_repos()['target']
    monkeypatch.setattr(runner, 'load_repos', lambda: {
        'target': replace(original, setup_cmd='', check_cmd=command)})
    try:
        if operation == 'build':
            subprocess.run(['git', '-C', str(repo), 'branch', 'stopped-candidate', base], check=True)
            monkeypatch.setattr(runner, 'candidates', lambda *a: [{
                'attempt_id': claim.attempt_id, 'branch': 'stopped-candidate', 'title': 'stop proof'}])
            result = runner.build_train(log, 'target')
            assert ': FAILED ' in result, result
            assert not [e['data'] for e in log.read() if e['type'] == 'train.built'][-1]['passed']
        else:
            _train(log, repo, 'stopped-check', base)
            if operation == 'recheck':
                worktree = Path([e['data'] for e in log.read()
                                 if e['type'] == 'train.built'][-1]['worktree'])
                subprocess.run(['git', '-C', str(repo), 'worktree', 'add', '--detach',
                                str(worktree), base], check=True, capture_output=True)
            if operation == 'historical':
                result = runner.land(log, 'tt')
                assert 'failed recheck; not landing' in result, result
                assert not [e for e in log.read() if e['type'] == 'item.landed']
                assert not [e['data'] for e in log.read() if e['type'] == 'train.built'][-1].get('checked_sha')
            else:
                result = runner.recheck_train(log, 'tt')
                assert 'FAILED' in result, result
                assert not [e['data'] for e in log.read() if e['type'] == 'train.built'][-1]['passed']
    finally:
        thread.join(25)
    assert not thread.is_alive()
    assert stops == [0]
    assert not done.exists()
    assert _head(repo) == base


@pytest.mark.parametrize('command,code,out,err', [
    ("printf '%s\\n' 'a b' \"quote'\";\nprintf '%s' stderr >&2", 0, "a b\nquote'\n", 'stderr'),
    ('exit 7', 7, '', ''),
    ('exec /bin/sh -c "exit 9"', 9, '', ''),
    ('timeout .1s sleep 10', 124, '', ''),
    ('head -c 262144 /dev/zero | tr "\\0" x', 0, 'x' * 262144, ''),
])
def test_namespace_completion_preserves_shell_results(estate, tmp_path, command, code, out, err):
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    result = runner._train_command(runner.load_repos()['target'], checkout, command)
    assert (result.returncode, result.stdout, result.stderr) == (code, out, err)


def test_namespace_start_deadline_fails_without_late_completion(estate, monkeypatch, tmp_path):
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    done = checkout / 'done'
    original = sandbox.for_train
    monkeypatch.setattr(sandbox, 'for_train', lambda **kw: replace(original(**kw), timeout_s=1))
    result = runner._train_command(runner.load_repos()['target'], checkout,
                                   f'sleep 10; touch {shlex.quote(str(done))}')
    assert result.returncode != 0
    assert not done.exists()
