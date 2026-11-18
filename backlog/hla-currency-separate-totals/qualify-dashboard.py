#!/usr/bin/env python3
"""Owner-side named lanectl namespace qualification with exact cgroup proof."""
import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import uuid

from lanectl.config import home, load_repos
from lanectl.events import state_dir
from lanectl.sandbox import for_train, transport_environment

parser = argparse.ArgumentParser()
parser.add_argument('--checkout', required=True)
parser.add_argument('--evidence', required=True)
parser.add_argument('--control', choices=('clean', 'detached', 'failure', 'wait'))
args = parser.parse_args()
checkout = Path(args.checkout).resolve()
evidence = Path(args.evidence)
if not evidence.is_absolute() or evidence.exists():
    sys.exit('Evidence must be a new absolute path')
repo = load_repos()['homelab-analytics']
if repo.train_isolation != 'namespace':
    sys.exit('Namespace train isolation is required')
unit = 'currency-ui-qualification-' + uuid.uuid4().hex
print('NAMED_UNIT ' + unit + '.service', flush=True)
sandbox = replace(for_train(readonly=(str(state_dir().resolve()), str(home().resolve()),
                                    str(Path(repo.path).resolve()),),
                            writable=(str(checkout),), timeout_s=300), unit=unit)
transport = transport_environment()
root = Path(__file__).resolve().parent
tracked = [root / 'run-dashboard.sh', root / 'process-groups.sh', Path(__file__).resolve(),
           *sorted((root / 'files/tests').glob('*.py')),
           root / 'files/apps/web/frontend/playwright/currency-separate-totals.spec.js']

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def git(*argv):
    return subprocess.run(['git', *argv], cwd=checkout, check=True, text=True, capture_output=True).stdout.strip()

sha = None
hashes = {str(p): digest(p) for p in tracked}
if not args.control:
    sha = git('rev-parse', 'HEAD')
    if git('status', '--porcelain=v1', '--untracked-files=all'):
        sys.exit('Candidate checkout must be clean')
    for p in (root / 'files').rglob('*'):
        if p.is_file() and '__pycache__' not in p.parts:
            candidate = checkout / p.relative_to(root / 'files')
            if not candidate.is_file() or digest(candidate) != digest(p):
                sys.exit(f'Candidate acceptance file differs: {candidate}')
    required = ['CURRENCY_ACCEPTANCE_POSTGRES_DSN', 'CURRENCY_ACCEPTANCE_HTTP_PORT',
                'CURRENCY_ACCEPTANCE_WEB_PORT', 'CURRENCY_ACCEPTANCE_UI_REPORT']
    for key in required:
        if not os.environ.get(key): sys.exit(f'{key} is required')
    report = Path(os.environ['CURRENCY_ACCEPTANCE_UI_REPORT'])
    if not report.is_absolute() or any(Path(str(report)+s).exists() for s in ('', '.mixed.json', '.disjoint.json', '.scenario-eur.json', '.scenario-usd.json')):
        sys.exit('UI report and sidecars must be new absolute paths')
else:
    report = None

interrupted = None

def on_signal(signum, _frame):
    global interrupted
    interrupted = signum

signal.signal(signal.SIGINT, on_signal)
signal.signal(signal.SIGTERM, on_signal)

def systemctl(*cmd):
    return subprocess.run(['systemctl', '--user', *cmd], env=transport, capture_output=True, text=True, timeout=20)

def read_properties():
    result = systemctl('show', unit + '.service', '--property=ControlGroup,KillMode,SendSIGKILL,TimeoutStopUSec,ActiveState,LoadState')
    if result.returncode != 0: return {}
    return dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)


def stop_unit():
    try:
        if systemctl('stop', unit + '.service').returncode == 0:
            return True
    except (OSError, subprocess.TimeoutExpired):
        pass
    # A failed stop never becomes success, even if this emergency kill works.
    try:
        systemctl('kill', '--kill-whom=all', '--signal=KILL', unit + '.service')
    except (OSError, subprocess.TimeoutExpired):
        pass
    return False

with tempfile.TemporaryDirectory(prefix='.currency-ui-owner-', dir=checkout) as temp:
    directory = Path(temp)
    ready, go, detached = (directory / n for n in ('ready', 'go', 'detached'))
    if args.control == 'clean':
        payload = 'exit 0'
    elif args.control:
        # Real detached process ignores TERM; systemd must kill it at unit end.
        code = ('import os,signal,time,pathlib; signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                f'pathlib.Path({str(detached)!r}).write_text(str(os.getpid())); time.sleep(120)')
        payload = f"setsid {shlex.quote(sys.executable)} -c {shlex.quote(code)} </dev/null >/dev/null 2>&1 & "
        payload += f"while [ ! -s {shlex.quote(str(detached))} ]; do sleep .05; done; "
        payload += {'detached': 'exit 0', 'failure': 'exit 23', 'wait': 'while :; do sleep 1; done'}[args.control]
    else:
        forwarded = ['CURRENCY_ACCEPTANCE_POSTGRES_DSN', 'CURRENCY_ACCEPTANCE_HTTP_PORT',
                     'CURRENCY_ACCEPTANCE_WEB_PORT', 'CURRENCY_ACCEPTANCE_UI_REPORT',
                     'PLAYWRIGHT_BROWSERS_PATH', 'LD_LIBRARY_PATH']
        prefix = ' '.join(f'{key}={shlex.quote(os.environ[key])}' for key in forwarded if os.environ.get(key))
        payload = f'{prefix} bash {shlex.quote(str(root / "run-dashboard.sh"))}'
    command = f'touch {shlex.quote(str(ready))}; while [ ! -f {shlex.quote(str(go))} ]; do sleep .05; done; {payload}'
    with tempfile.TemporaryFile(mode='w+t') as output:
        proc = subprocess.Popen(sandbox.wrap_shell(command, checkout), shell=True, cwd=checkout,
                                env=transport, stdout=output, stderr=subprocess.STDOUT, text=True)
        cgroup = None
        props = {}
        initial = {}
        problem = None
        try:
            deadline = time.monotonic() + 20
            while not ready.exists() and proc.poll() is None and interrupted is None and time.monotonic() < deadline:
                time.sleep(.05)
            if not ready.exists() or interrupted is not None:
                problem = 'named unit did not reach fenced handshake'
            else:
                props = read_properties()
                cgroup = props.get('ControlGroup')
                if (not cgroup or not cgroup.startswith('/') or props.get('KillMode') != 'control-group'
                        or props.get('SendSIGKILL') != 'yes' or props.get('TimeoutStopUSec') in (None, '', 'infinity')):
                    problem = f'unacceptable or unobservable unit policy: {props}'
                else:
                    group_path = Path('/sys/fs/cgroup') / cgroup.lstrip('/')
                    try:
                        initial = dict(line.split() for line in (group_path / 'cgroup.events').read_text().splitlines())
                    except (OSError, ValueError):
                        initial = {}
                    if initial.get('populated') != '1':
                        problem = 'named unit cgroup was not observable and populated during execution'
                    else:
                        go.touch()
            deadline = time.monotonic() + 330
            while proc.poll() is None and interrupted is None and problem is None and time.monotonic() < deadline:
                time.sleep(.05)
            if proc.poll() is None:
                if not stop_unit(): problem = 'could not stop named unit'
            try:
                rc = proc.wait(timeout=25)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.wait(timeout=5); problem = 'named unit launcher did not settle'
            if cgroup:
                group_path = Path('/sys/fs/cgroup') / cgroup.lstrip('/')
                deadline = time.monotonic() + 20
                settled = False
                while time.monotonic() < deadline:
                    try:
                        events = dict(line.split() for line in (group_path / 'cgroup.events').read_text().splitlines())
                        settled = events.get('populated') == '0'
                    except FileNotFoundError:
                        settled = True
                    if settled: break
                    time.sleep(.05)
                if not settled: problem = 'exact named unit cgroup did not settle'
            else:
                settled = False
        finally:
            if proc.poll() is None:
                if not stop_unit(): problem = 'could not stop named unit'
                try: proc.wait(timeout=25)
                except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=5)
        output.seek(0)
        captured = output.read()
    detached_pid = int(detached.read_text()) if detached.exists() else None
    if args.control and detached_pid is not None:
        try:
            state = Path(f'/proc/{detached_pid}/stat').read_text().rsplit(')', 1)[1].split()[0]
            if state not in ('Z', 'X'): problem = 'detached control child remains alive'
        except FileNotFoundError:
            pass
    observation = {'unit': unit + '.service', 'policy': props, 'cgroup': cgroup,
                   'initial_cgroup_events': initial, 'settled': settled, 'exit_code': rc, 'interrupted': interrupted,
                   'detached_control_pid': detached_pid, 'problem': problem}
    print(captured, end='')
    print('OUTER_OBSERVATION ' + json.dumps(observation, sort_keys=True))
    if interrupted is not None or problem or not settled or rc != 0:
        sys.exit(128 + interrupted if interrupted else 1)
    if args.control:
        if args.control != 'clean' and detached_pid is None: sys.exit('detached control did not execute')
        evidence.write_text(json.dumps({'kind': 'currency-ui-cgroup-control/v1', **observation}, indent=2) + '\n')
        sys.exit(0)
    if not report.is_file(): sys.exit('validated UI report missing')
    payload_hash = hashlib.sha256(report.read_bytes()).hexdigest()
# Owner handshake files have now been removed; source binding must still hold.
if (git('rev-parse', 'HEAD') != sha or git('status', '--porcelain=v1', '--untracked-files=all')
        or hashes != {str(p): digest(p) for p in tracked}):
    sys.exit('Candidate or criterion changed; UI evidence rejected')
evidence.write_text(json.dumps({'kind': 'hla-currency-ui-qualification/v1', 'candidate_commit': sha,
                                'source_sha256': hashes, 'ui_report_sha256': payload_hash,
                                **observation}, indent=2) + '\n')
