"""Force timeout and cancellation; verify exact owned cleanup and refusal paths."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from unittest.mock import patch

from ownership import append, birth, cleanup
from run_candidate import supervise

HERE = Path(__file__).resolve().parent


def run_child(output, timeout):
    env = dict(os.environ, PYTHONPATH=str(HERE))
    return supervise(['uv', 'run', '--no-sync', 'python', str(HERE / 'fake_owned_child.py')], Path('/tmp/hla-api-a7-qualification'), env, output, 'control-token', timeout=timeout)


def check_record(output, kind):
    record = json.loads((output / 'lifecycle.json').read_text())
    assert record['primary']['kind'] == kind, record
    assert record['cleanup']['verified'], record
    actions = record['cleanup']['actions']
    assert any(item.get('container') and item.get('absent') for item in actions), actions
    assert any(item.get('process') and item.get('absent') for item in actions), actions
    assert 'child created owned container and process' in (output / 'stdout.log').read_text()
    assert 'synthetic partial diagnostic' in (output / 'stderr.log').read_text()
    return record


def main():
    with tempfile.TemporaryDirectory(prefix='hla-owner-controls-') as directory:
        root = Path(directory)
        timeout_dir = root / 'timeout'
        timeout_dir.mkdir()
        result = run_child(timeout_dir, 5)
        assert result['primary']['kind'] == 'timeout', result
        check_record(timeout_dir, 'timeout')
        print('timeout: primary preserved; exact container and PID/birth group absent')
        cancel_dir = root / 'cancel'
        cancel_dir.mkdir()
        driver = subprocess.Popen([sys.executable, __file__, '--driver', str(cancel_dir)], env=dict(os.environ, PYTHONPATH=str(HERE)), start_new_session=True)
        try:
            ledger = cancel_dir / 'ownership.jsonl'
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if ledger.exists() and '"type": "process"' in ledger.read_text() and '"type": "container_started"' in ledger.read_text():
                    break
                assert driver.poll() is None, 'cancel driver exited before ready'
                time.sleep(.1)
            else:
                raise AssertionError('cancel driver did not create owned resources')
            os.kill(driver.pid, signal.SIGTERM)
            assert driver.wait(timeout=40) == 0
            check_record(cancel_dir, 'cancelled')
            print('cancel: primary preserved; exact container and PID/birth group absent')
        finally:
            if driver.poll() is None:
                os.killpg(driver.pid, signal.SIGKILL)
                driver.wait()
        bad = root / 'bad-ledger.jsonl'
        append(bad, {'type': 'observer_ready', 'token': 'control-token'})
        sleeper = subprocess.Popen(['sleep', '120'], start_new_session=True)
        try:
            append(bad, {'type': 'process', 'pid': sleeper.pid, 'birth': str(int(birth(sleeper.pid)) + 1), 'pgid': sleeper.pid})
            denied = cleanup(bad, 'control-token')
            assert not denied['verified'] and any('mismatch' in value for value in denied['failures']), denied
            assert sleeper.poll() is None, 'mismatched process was signalled'
            print('bad process birth: cleanup refused and reported failure')
        finally:
            os.killpg(sleeper.pid, signal.SIGTERM)
            sleeper.wait()
        daemon = root / 'daemon-ledger.jsonl'
        append(daemon, {'type': 'observer_ready', 'token': 'control-token'})
        append(daemon, {'type': 'container_planned', 'name': 'synthetic-owned', 'token': 'control-token', 'preexisting_absent': True})
        unavailable = subprocess.CompletedProcess(['docker'], 1, '', 'synthetic daemon unavailable')
        with patch('ownership.subprocess.run', return_value=unavailable) as command:
            denied = cleanup(daemon, 'control-token')
        assert not denied['verified'] and any('inventory failed' in value for value in denied['failures']), denied
        assert command.call_count == 1 and command.call_args.args[0][1:3] == ['ps', '-a'], command.call_args_list
        print('daemon inventory failure: cleanup refused and reported failure')
        wrong_label = root / 'wrong-label-ledger.jsonl'
        append(wrong_label, {'type': 'observer_ready', 'token': 'control-token'})
        name = 'hla-ui-label-control-' + uuid.uuid4().hex[:12]
        image = 'sha256:b0ab6f3cb99aa7803adbc14d9027ec1785fc6e433b97e134e0f8fe61683b6b53'
        cid = subprocess.check_output(['docker', 'run', '-d', '--name', name, '--network', 'none', '--label',
                                       'hla.ui.qual.owner=wrong-token', image, 'node', '-e', 'setInterval(()=>{},1000)'], text=True).strip()
        try:
            append(wrong_label, {'type': 'container_planned', 'name': name, 'token': 'control-token', 'preexisting_absent': True})
            append(wrong_label, {'type': 'container_started', 'name': name, 'cid': cid, 'token': 'control-token'})
            denied = cleanup(wrong_label, 'control-token')
            assert not denied['verified'] and any('identity/label mismatch' in value for value in denied['failures']), denied
            assert subprocess.run(['docker', 'inspect', cid], capture_output=True).returncode == 0
            print('wrong container label: cleanup refused and reported failure')
        finally:
            subprocess.run(['docker', 'rm', '-f', cid], capture_output=True)
            inventory = subprocess.run(['docker', 'ps', '-a', '--no-trunc', '--format', '{{.ID}}'], capture_output=True, text=True)
            assert inventory.returncode == 0 and cid not in inventory.stdout.splitlines()
        corrupt = root / 'corrupt-ledger.jsonl'
        corrupt.write_text('{broken\n')
        denied = cleanup(corrupt, 'control-token')
        assert not denied['verified'] and denied['failures'], denied
        print('malformed ledger: cleanup failure recorded')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--driver':
        result = run_child(Path(sys.argv[2]), 60)
        raise SystemExit(0 if result['primary']['kind'] == 'cancelled' and result['cleanup']['verified'] else 1)
    main()
