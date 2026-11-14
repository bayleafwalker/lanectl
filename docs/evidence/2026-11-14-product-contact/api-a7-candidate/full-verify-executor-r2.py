"""Full verification of the genuine API candidate with an owned matched browser."""
import json
import os
import shlex
import subprocess
import time
from pathlib import Path
from lanectl.config import load_repos
from lanectl.runner import _train_command

checkout = Path('/tmp/hla-api-a7-qualification')
expected = '01733b1024f6b6f779282a9b1181b646c1e27db6'
output = Path('/tmp/hla-api-a7-full-verify-r2')
output.mkdir(mode=0o700, exist_ok=False)
browser_name = 'hla-api-r4-a7-browser-r2'
browser_id = None
result = None

def command(argv):
    return subprocess.check_output(argv, text=True).strip()

def clean():
    assert command(['git', '-C', str(checkout), 'rev-parse', 'HEAD']) == expected
    assert not command(['git', '-C', str(checkout), 'status', '--porcelain', '--untracked-files=all'])

def save(name, value):
    (output / name).write_text(json.dumps(value, indent=2) + '\n')

try:
    clean()
    repo = load_repos(Path('/projects/dev/lanectl'))['homelab-analytics']
    assert repo.train_isolation == 'namespace'
    setup = _train_command(repo, checkout, repo.setup_cmd)
    save('setup.json', {'command': repo.setup_cmd, 'returncode': setup.returncode,
                        'stdout': setup.stdout, 'stderr': setup.stderr})
    assert setup.returncode == 0, 'candidate environment setup failed'
    clean()
    assert json.loads((checkout / 'apps/web/frontend/node_modules/playwright/package.json').read_text())['version'] == '1.59.1'
    for port in ('34155', '6006'):
        assert not command(['ss', '-H', '-ltn', 'sport = :' + port]), 'verification port occupied: ' + port
    assert browser_name not in command(['docker', 'ps', '-a', '--format', '{{.Names}}']).splitlines()
    image = command(['docker', 'image', 'inspect', 'mcr.microsoft.com/playwright:v1.59.1-noble', '--format', '{{.Id}}'])
    assert image == 'sha256:b0ab6f3cb99aa7803adbc14d9027ec1785fc6e433b97e134e0f8fe61683b6b53'
    modules = checkout / 'apps/web/frontend/node_modules'
    browser_id = command(['docker', 'run', '-d', '--name', browser_name,
        '--network', 'host', '--ipc=host', '-v', str(modules) + ':/opt/node_modules:ro',
        image, 'node', '/opt/node_modules/playwright/cli.js', 'run-server',
        '--host', '127.0.0.1', '--port', '34155'])
    assert len(browser_id) == 64 and all(c in '0123456789abcdef' for c in browser_id)
    logs = ''
    for _ in range(20):
        probe = subprocess.run(['docker', 'logs', browser_id], capture_output=True, text=True)
        logs = probe.stdout + probe.stderr
        if 'Listening on ws://127.0.0.1:34155/' in logs:
            break
        state = json.loads(command(['docker', 'inspect', browser_id]))[0]['State']
        if not state['Running']:
            break
        time.sleep(0.5)
    save('browser-start.json', {'name': browser_name, 'container_id': browser_id,
                               'image': image, 'logs': logs})
    assert 'Listening on ws://127.0.0.1:34155/' in logs, logs
    prefix = '/nix/store/71c91xjkcj07khl9imgmgji5wzrxwy65-gnumake-4.4.1/bin:/projects/dev/homelab-analytics/.tooling/node-v20.20.1-linux-x64/bin'
    shell = 'PATH=' + shlex.quote(prefix) + ':"$PATH" XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus PW_TEST_CONNECT_WS_ENDPOINT=ws://127.0.0.1:34155/ make verify-fast'
    started = time.monotonic()
    result = _train_command(repo, checkout, shell)
    clean()
    record = {'source_sha': expected, 'isolation': repo.train_isolation, 'command': shell,
              'elapsed_s': round(time.monotonic() - started, 2), 'returncode': result.returncode,
              'stdout': result.stdout, 'stderr': result.stderr,
              'browser': 'Playwright1.59.1 Ubuntu noble, unchanged snapshots/tolerances'}
    save('verify-fast.json', record)
    (output / 'verify-fast.log').write_text(result.stdout + '\n' + result.stderr)
    print(json.dumps({k: v for k, v in record.items() if k not in ('stdout', 'stderr')}), flush=True)
except BaseException as exc:
    save('executor-error.json', {'type': type(exc).__name__, 'message': str(exc)})
    raise
finally:
    if browser_id:
        removed = subprocess.run(['docker', 'rm', '-f', browser_id], capture_output=True, text=True)
        inventory = subprocess.run(['docker', 'ps', '-a', '--no-trunc', '--format', '{{.ID}}'], capture_output=True, text=True)
        absent = inventory.returncode == 0 and browser_id not in inventory.stdout.splitlines()
        save('browser-cleanup.json', {'name': browser_name, 'container_id': browser_id,
            'remove_status': removed.returncode, 'inventory_status': inventory.returncode,
            'absent': absent, 'remove_stderr': removed.stderr, 'inventory_stderr': inventory.stderr})
        assert absent, 'owned browser absence could not be proved'
if result is None or result.returncode:
    raise SystemExit(1)
