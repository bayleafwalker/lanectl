"""Exercise named-unit completion, detached escalation, failure and cancellation."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

if len(sys.argv) != 2:
    sys.exit('usage: test-named-cgroup.py /absolute/path/to/owned-hla-checkout')
checkout = Path(sys.argv[1]).resolve()
driver = Path(__file__).resolve().parent / 'qualify-legacy.py'
with tempfile.TemporaryDirectory(prefix='currency-named-controls-') as folder:
    root = Path(folder)
    for mode in ('clean', 'detached', 'failure', 'int', 'term'):
        before = set(checkout.glob('.currency-legacy-owner-*/detached'))
        evidence = root / (mode + '.json')
        control = 'wait' if mode in ('int', 'term') else mode
        with tempfile.TemporaryFile(mode='w+t') as output:
            process = subprocess.Popen([sys.executable, str(driver), '--checkout', str(checkout),
                                        '--evidence', str(evidence), '--control', control],
                                       stdout=output, stderr=subprocess.STDOUT, text=True)
            try:
                if mode in ('int', 'term'):
                    deadline = time.monotonic() + 20
                    while time.monotonic() < deadline:
                        if set(checkout.glob('.currency-legacy-owner-*/detached')) - before: break
                        if process.poll() is not None: break
                        time.sleep(.05)
                    assert set(checkout.glob('.currency-legacy-owner-*/detached')) - before, f'{mode}: control child did not start'
                    os.kill(process.pid, signal.SIGINT if mode == 'int' else signal.SIGTERM)
                rc = process.wait(timeout=45)
                output.seek(0)
                text = output.read()
                line = next(x for x in text.splitlines() if x.startswith('OUTER_OBSERVATION '))
                result = json.loads(line[len('OUTER_OBSERVATION '):])
                assert result['settled'] is True and result['cgroup'] and result['problem'] is None, result
                assert result['initial_cgroup_events']['populated'] == '1', result
                assert result['policy']['KillMode'] == 'control-group' and result['policy']['SendSIGKILL'] == 'yes', result
                if mode == 'clean':
                    assert rc == 0 and evidence.exists(), (mode, rc, text)
                else:
                    assert rc != 0 and not evidence.exists() and result['detached_control_pid'], (mode, rc, text)
                print(mode, 'exit', rc, json.dumps(result, sort_keys=True), flush=True)
            finally:
                if process.poll() is None:
                    output.seek(0)
                    for line in output:
                        if line.startswith('NAMED_UNIT '):
                            subprocess.run(['systemctl', '--user', 'stop', line.split()[1]],
                                           timeout=25, check=False, capture_output=True)
                    process.kill()
                    process.wait(timeout=5)
