#!/usr/bin/env python3
"""Owner-side named-unit qualification of an existing reporting-store upgrade."""
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
import xml.etree.ElementTree as ET

from lanectl.config import home, load_repos
from lanectl.events import state_dir
from lanectl.sandbox import for_train, transport_environment

parser = argparse.ArgumentParser()
parser.add_argument('--checkout', required=True)
parser.add_argument('--evidence', required=True)
parser.add_argument('--warehouse')
parser.add_argument('--manifest')
parser.add_argument('--ui-report')
parser.add_argument('--control', choices=('clean', 'detached', 'failure', 'wait'))
args = parser.parse_args()
checkout = Path(args.checkout).resolve()
evidence = Path(args.evidence)
if not evidence.is_absolute() or evidence.exists():
    sys.exit('Evidence must be a new absolute path')
repo = load_repos()['homelab-analytics']
if repo.train_isolation != 'namespace':
    sys.exit('Namespace train isolation is required')
unit = 'currency-legacy-qualification-' + uuid.uuid4().hex
print('NAMED_UNIT ' + unit + '.service', flush=True)
sandbox = replace(for_train(readonly=(str(state_dir().resolve()), str(home().resolve()),
                                    str(Path(repo.path).resolve()),),
                            writable=(str(checkout),), timeout_s=1800), unit=unit)
transport = transport_environment()
root = Path(__file__).resolve().parent
tracked = [Path(__file__).resolve(),
           *sorted((root / 'files/tests').glob('*.py')),
           root / 'files/apps/web/frontend/playwright/currency-separate-totals.spec.js',
           root / 'files/apps/web/frontend/playwright/currency-legacy-history.spec.js']

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
    required = ['CURRENCY_LEGACY_POSTGRES_DSN', 'CURRENCY_LEGACY_PG_DUMP',
                'CURRENCY_LEGACY_API_PORT', 'CURRENCY_LEGACY_WEB_PORT']
    for key in required:
        if not os.environ.get(key): sys.exit(f'{key} is required')
    if not args.warehouse or not args.manifest or not args.ui_report:
        sys.exit('Existing legacy warehouse, manifest and new UI report path are required')
    warehouse, manifest = Path(args.warehouse).resolve(), Path(args.manifest).resolve()
    if not warehouse.is_file() or not manifest.is_file() or warehouse.is_relative_to(checkout) or manifest.is_relative_to(checkout):
        sys.exit('Legacy warehouse and manifest must be existing files outside the candidate checkout')
    seed = json.loads(manifest.read_text())
    if seed.get('kind') != 'hla-currency-legacy-fixture/v2' or seed.get('source_commit') != '82dbd9477029d6fda7df67edc617f45a1a4ceb59':
        sys.exit('Incorrect legacy fixture kind or historical source')
    if seed.get('fixture_sha256') != digest(root / 'files/tests/currency_legacy_fixture.py') or seed.get('oracle_sha256') != digest(root / 'files/tests/currency_legacy_oracle.py'):
        sys.exit('Legacy fixture or oracle differs from the seeded bytes')
    if seed.get('warehouse_sha256') != digest(warehouse):
        sys.exit('Legacy warehouse differs from the sealed original fixture')
    manifest_hash = digest(manifest)
    extra_bindings = {}
    schemas = {seed['postgres_schema']}
    warehouses = {warehouse}
    for label in ('DRIFT', 'DEPENDENCY', 'OUTAGE'):
        wk, mk = f'CURRENCY_LEGACY_{label}_WAREHOUSE', f'CURRENCY_LEGACY_{label}_MANIFEST'
        if not os.environ.get(wk) or not os.environ.get(mk):
            sys.exit(f'{wk} and {mk} are required for independent adversarial fixtures')
        w, m = Path(os.environ[wk]).resolve(), Path(os.environ[mk]).resolve()
        if not w.is_file() or not m.is_file() or w.is_relative_to(checkout) or m.is_relative_to(checkout) or w in warehouses:
            sys.exit('Adversarial warehouses and manifests must be distinct existing files outside checkout')
        item = json.loads(m.read_text())
        if (item.get('kind') != seed['kind'] or item.get('source_commit') != seed['source_commit']
                or item.get('fixture_sha256') != seed['fixture_sha256'] or item.get('oracle_sha256') != seed['oracle_sha256']
                or item.get('warehouse_sha256') != digest(w) or item.get('postgres_schema') in schemas):
            sys.exit('Adversarial fixture source, schema or warehouse binding is invalid')
        os.environ[wk], os.environ[mk] = str(w), str(m)
        schemas.add(item['postgres_schema'])
        warehouses.add(w)
        extra_bindings[label] = {'manifest': str(m), 'manifest_sha256': digest(m), 'warehouse': str(w),
                                 'warehouse_before_sha256': item['warehouse_sha256']}
    ui_report = Path(args.ui_report)
    first_ui_report = Path(str(ui_report) + '.first')
    if not ui_report.is_absolute() or ui_report.exists() or first_ui_report.exists() or ui_report.is_relative_to(checkout):
        sys.exit('UI report must be a new absolute path outside the checkout')
    report = None
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

with tempfile.TemporaryDirectory(prefix='.currency-legacy-owner-', dir=checkout) as temp:
    directory = Path(temp)
    ready, go, detached = (directory / n for n in ('ready', 'go', 'detached'))
    junit = directory / 'legacy-result.xml'
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
        forwarded = ['CURRENCY_LEGACY_POSTGRES_DSN', 'CURRENCY_LEGACY_PG_DUMP',
                     'CURRENCY_LEGACY_API_PORT', 'CURRENCY_LEGACY_WEB_PORT',
                     'PLAYWRIGHT_BROWSERS_PATH', 'LD_LIBRARY_PATH',
                     *[f'CURRENCY_LEGACY_{label}_{kind}' for label in ('DRIFT', 'DEPENDENCY', 'OUTAGE') for kind in ('WAREHOUSE', 'MANIFEST')]]
        prefix = ' '.join(f'{key}={shlex.quote(os.environ[key])}' for key in forwarded if os.environ.get(key))
        prefix += f' CURRENCY_LEGACY_WAREHOUSE={shlex.quote(str(warehouse))} CURRENCY_LEGACY_MANIFEST={shlex.quote(str(manifest))} CURRENCY_LEGACY_UI_REPORT={shlex.quote(str(ui_report))}'
        target = 'tests/test_acc_currency_legacy_upgrade.py::test_legacy_upgrade_preserves_facts_snapshots_and_published_currency'
        payload = f'{prefix} .venv/bin/python -m pytest -q -p no:cacheprovider --junitxml={shlex.quote(str(junit))} {target}'
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
            deadline = time.monotonic() + 1830
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
        evidence.write_text(json.dumps({'kind': 'currency-legacy-cgroup-control/v1', **observation}, indent=2) + '\n')
        sys.exit(0)
    try:
        report = ET.parse(junit).getroot()
        cases = list(report.iter('testcase'))
        suites = list(report.iter('testsuite'))
        valid = (len(cases) == 1 and bool(suites)
                 and cases[0].get('name') == 'test_legacy_upgrade_preserves_facts_snapshots_and_published_currency'
                 and cases[0].get('classname', '').split('.')[-1] == 'test_acc_currency_legacy_upgrade'
                 and not any(cases[0].find(tag) is not None for tag in ('failure', 'error', 'skipped'))
                 and all(int(suite.get(tag, '0')) == 0 for suite in suites for tag in ('errors', 'failures', 'skipped'))
                 and all(int(suite.get('tests', '-1')) == 1 for suite in suites))
    except (OSError, ET.ParseError, ValueError):
        valid = False
    if not valid: sys.exit('Exact legacy candidate test did not execute and pass; evidence rejected')
    junit_bytes = junit.read_bytes()
    junit_hash = hashlib.sha256(junit_bytes).hexdigest()
    if not ui_report.is_file() or not first_ui_report.is_file(): sys.exit('Both legacy browser results are required; evidence rejected')
    ui_report_hash = digest(ui_report)
    first_ui_report_hash = digest(first_ui_report)
# Owner handshake files have now been removed; source binding must still hold.
if (git('rev-parse', 'HEAD') != sha or git('status', '--porcelain=v1', '--untracked-files=all')
        or hashes != {str(p): digest(p) for p in tracked} or digest(manifest) != manifest_hash
        or any(digest(Path(item['manifest'])) != item['manifest_sha256'] for item in extra_bindings.values())):
    sys.exit('Candidate or criterion changed; UI evidence rejected')
junit_artifact = Path(str(evidence) + '.junit.xml')
with junit_artifact.open('xb') as out:
    out.write(junit_bytes)
evidence.write_text(json.dumps({'kind': 'hla-currency-legacy-upgrade-qualification/v1', 'candidate_commit': sha,
                                'source_sha256': hashes, 'legacy_manifest_sha256': manifest_hash,
                                'legacy_warehouse_before_sha256': seed['warehouse_sha256'], 'adversarial_fixtures': extra_bindings, 'junit_sha256': junit_hash,
                                'junit_path': str(junit_artifact), 'ui_report_sha256': ui_report_hash,
                                'first_ui_report_sha256': first_ui_report_hash,
                                **observation}, indent=2) + '\n')
