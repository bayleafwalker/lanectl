"""Parent-readable ownership ledger and exact-resource cleanup for scratch tests."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path

LABEL = 'hla.ui.qual.owner'


def append(path: Path, event: dict) -> None:
    payload = (json.dumps(event, sort_keys=True) + '\n').encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)


def birth(pid: int) -> str:
    text = Path(f'/proc/{pid}/stat').read_text()
    return text[text.rfind(')') + 2:].split()[19]


def install(ledger: Path, token: str) -> None:
    """Observe owned Docker and Next starts inside this disposable pytest process."""
    original_run, original_popen = subprocess.run, subprocess.Popen
    append(ledger, {'type': 'observer_ready', 'token': token})

    class MonitoredPopen(original_popen):
        def __init__(self, args, *pos, **kwargs):
            is_next = isinstance(args, (list, tuple)) and len(args) > 1 and str(args[0]).endswith('/next') and args[1] == 'start'
            delayed, prior = [], {}
            if is_next:
                child_env = kwargs.get('env') if kwargs.get('env') is not None else os.environ
                kwargs['env'] = {key: value for key, value in child_env.items()
                                 if key not in {'HLA_UI_QUAL_LEDGER', 'HLA_UI_QUAL_TOKEN'}}
                for sig in (signal.SIGINT, signal.SIGTERM):
                    prior[sig] = signal.getsignal(sig)
                    signal.signal(sig, lambda number, _frame: delayed.append(number))
            try:
                super().__init__(args, *pos, **kwargs)
                if is_next:
                    try:
                        event = {'type': 'process', 'pid': self.pid, 'birth': birth(self.pid), 'pgid': os.getpgid(self.pid)}
                        append(ledger, event)
                    except (OSError, ValueError) as exc:
                        append(ledger, {'type': 'process_unverified', 'pid': self.pid, 'error': str(exc)})
                        raise
            finally:
                for sig, handler in prior.items():
                    signal.signal(sig, handler)
                if delayed:
                    os.kill(os.getpid(), delayed[0])

    def monitored_run(args, *pos, **kwargs):
        if isinstance(args, list) and args[:2] == ['docker', 'run'] and '--name' in args:
            name = args[args.index('--name') + 1]
            check = original_run(['docker', 'ps', '-a', '--format', '{{.Names}}'], capture_output=True, text=True, timeout=20)
            if check.returncode != 0 or name in check.stdout.splitlines():
                raise RuntimeError('cannot prove unique owned container name')
            append(ledger, {'type': 'container_planned', 'name': name, 'token': token, 'preexisting_absent': True})
            args = [*args[:2], '--label', f'{LABEL}={token}', *args[2:]]
            result = original_run(args, *pos, **kwargs)
            cid = result.stdout.decode().strip() if isinstance(result.stdout, bytes) else (result.stdout or '').strip()
            if result.returncode == 0 and len(cid) == 64:
                append(ledger, {'type': 'container_started', 'name': name, 'cid': cid, 'token': token})
            return result
        return original_run(args, *pos, **kwargs)

    subprocess.Popen = MonitoredPopen
    subprocess.run = monitored_run


def cleanup(ledger: Path, token: str) -> dict:
    """Remove only resources whose exact ownership can be reverified."""
    events, failures, actions = [], [], []
    try:
        if ledger.exists():
            events = [json.loads(line) for line in ledger.read_text().splitlines() if line]
    except (OSError, ValueError) as exc:
        failures.append(f'ledger unreadable: {exc}')
    if not any(event.get('type') == 'observer_ready' and event.get('token') == token for event in events):
        failures.append('scratch observer installation was not recorded')
    if any(event.get('type') == 'process_unverified' for event in events):
        failures.append('a started process lacked verified birth identity')
    for event in events:
        if event.get('type') != 'process':
            continue
        pid, expected_birth, pgid = event['pid'], event['birth'], event['pgid']
        try:
            actual_birth = birth(pid)
        except FileNotFoundError:
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                actions.append({'process': pid, 'absent': True})
            except (OSError, PermissionError) as exc:
                failures.append(f'process group {pgid} absence unverified: {exc}')
            else:
                failures.append(f'process leader {pid} gone but group {pgid} still exists; not signalled')
            continue
        except (OSError, ValueError) as exc:
            failures.append(f'process {pid} identity unreadable: {exc}')
            continue
        if actual_birth != expected_birth or os.getpgid(pid) != pgid or pgid != pid:
            failures.append(f'process {pid} birth/group mismatch; not signalled')
            continue
        try:
            os.killpg(pgid, signal.SIGTERM)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                try:
                    if birth(pid) != expected_birth:
                        break
                except FileNotFoundError:
                    break
                time.sleep(.1)
            else:
                if birth(pid) == expected_birth and os.getpgid(pid) == pgid:
                    os.killpg(pgid, signal.SIGKILL)
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                actions.append({'process': pid, 'absent': True})
            else:
                failures.append(f'process group {pgid} still exists after cleanup')
        except (OSError, ValueError) as exc:
            failures.append(f'process {pid} cleanup unverified: {exc}')
    planned = {event['name']: event for event in events if event.get('type') == 'container_planned'}
    started = {event['name']: event for event in events if event.get('type') == 'container_started'}
    for name, event in planned.items():
        if event.get('token') != token or event.get('preexisting_absent') is not True:
            failures.append(f'container {name} ledger ownership mismatch')
            continue
        try:
            inventory = subprocess.run(['docker', 'ps', '-a', '--no-trunc', '--format', '{{.ID}} {{.Names}}'], capture_output=True, text=True, timeout=20)
            if inventory.returncode != 0:
                failures.append(f'container {name} daemon inventory failed')
                continue
            matches = [line.split(' ', 1)[0] for line in inventory.stdout.splitlines() if line.endswith(' ' + name)]
            if not matches:
                actions.append({'container': name, 'absent': True})
                continue
            if len(matches) != 1:
                failures.append(f'container {name} ambiguous inventory')
                continue
            cid = matches[0]
            recorded = started.get(name, {}).get('cid')
            inspect = subprocess.run(['docker', 'inspect', cid], capture_output=True, text=True, timeout=20)
            if inspect.returncode != 0:
                failures.append(f'container {name} inspect failed')
                continue
            data = json.loads(inspect.stdout)[0]
            labels = data.get('Config', {}).get('Labels') or {}
            if data.get('Id') != cid or data.get('Name', '').lstrip('/') != name or labels.get(LABEL) != token or (recorded and recorded != cid):
                failures.append(f'container {name} identity/label mismatch; not removed')
                continue
            removed = subprocess.run(['docker', 'rm', '-f', cid], capture_output=True, text=True, timeout=30)
            after = subprocess.run(['docker', 'ps', '-a', '--no-trunc', '--format', '{{.ID}}'], capture_output=True, text=True, timeout=20)
            if removed.returncode != 0 or after.returncode != 0 or cid in after.stdout.splitlines():
                failures.append(f'container {name} removal/absence unverified')
            else:
                actions.append({'container': name, 'cid': cid, 'absent': True})
        except (OSError, ValueError, IndexError, subprocess.TimeoutExpired) as exc:
            failures.append(f'container {name} cleanup unverified: {type(exc).__name__}: {exc}')
    return {'actions': actions, 'failures': failures, 'verified': not failures}
