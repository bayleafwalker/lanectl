"""Run extra qualification with an exact-SHA checkout and owned-resource ledger."""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import signal
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from ownership import cleanup

EXPECTED = {
    'test_each_public_fact_has_correct_semantic_label_and_separate_row',
    'test_real_current_api_nonnull_market_reference_preserves_value_precision',
}
NODE = '/projects/dev/homelab-analytics/.tooling/node-v20.20.1-linux-x64/bin'


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


def supervise(command, cwd, env, output, token, timeout=600):
    """Preserve primary outcome, raw logs and verified cleanup on exit/cancel/timeout."""
    ledger = output / 'ownership.jsonl'
    env = dict(env, HLA_UI_QUAL_LEDGER=str(ledger), HLA_UI_QUAL_TOKEN=token, PYTHONUNBUFFERED='1')
    cancelled = []
    old_handlers = {}
    process = None
    primary = {'kind': 'not_started'}
    started = time.monotonic()
    try:
        with (output / 'stdout.log').open('w') as stdout, (output / 'stderr.log').open('w') as stderr:
            for sig in (signal.SIGINT, signal.SIGTERM):
                old_handlers[sig] = signal.getsignal(sig)
                signal.signal(sig, lambda number, _frame: cancelled.append(number))
            process = subprocess.Popen(command, cwd=cwd, env=env, text=True, stdout=stdout, stderr=stderr,
                                       start_new_session=True)
            deadline = time.monotonic() + timeout
            while process.poll() is None and not cancelled and time.monotonic() < deadline:
                time.sleep(.2)
            if process.poll() is None:
                primary = {'kind': 'cancelled' if cancelled else 'timeout', 'signal': cancelled[0] if cancelled else None}
                try:
                    os.killpg(process.pid, signal.SIGINT)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=10)
                    primary['forced_process_group_kill'] = True
            else:
                primary = ({'kind': 'cancelled', 'signal': cancelled[0]} if cancelled
                           else {'kind': 'exit', 'returncode': process.returncode})
    except BaseException as exc:
        if primary['kind'] in {'timeout', 'cancelled'}:
            primary['termination_error'] = f'{type(exc).__name__}: {exc}'
        else:
            primary = {'kind': 'executor_error', 'type': type(exc).__name__, 'message': str(exc)}
        if process and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGINT)
                process.wait(timeout=20)
            except (OSError, subprocess.TimeoutExpired):
                primary['child_exit_unverified'] = True
    try:
        cleanup_result = cleanup(ledger, token)
        if process and process.poll() is None:
            cleanup_result['verified'] = False
            cleanup_result['failures'].append('supervised child exit unverified; additional resources may appear')
    except BaseException as exc:
        cleanup_result = {'verified': False, 'actions': [], 'failures': [f'cleanup raised {type(exc).__name__}: {exc}']}
    if cancelled and primary['kind'] == 'exit':
        primary = {'kind': 'cancelled', 'signal': cancelled[0], 'child_returncode': primary['returncode']}
    record = {'primary': primary, 'cleanup': cleanup_result, 'elapsed_seconds': round(time.monotonic() - started, 2)}
    try:
        (output / 'lifecycle.json').write_text(json.dumps(record, indent=2) + '\n')
    finally:
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
    return record


def validate_junit(report):
    root = ET.parse(report).getroot()
    suites, cases = list(root.iter('testsuite')), list(root.iter('testcase'))
    names = [case.get('name') for case in cases]
    assert root.tag in ('testsuite', 'testsuites') and len(suites) == 1
    assert len(cases) == 2 and set(names) == EXPECTED
    assert all(int(suites[0].attrib[k]) == v for k, v in (('tests', 2), ('skipped', 0), ('failures', 0), ('errors', 0)))
    assert not any(list(root.iter(tag)) for tag in ('failure', 'error', 'skipped'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--checkout', type=Path, required=True)
    parser.add_argument('--sha', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    checkout, output = args.checkout.resolve(), args.output.resolve()
    assert checkout.is_relative_to('/tmp') and output.is_relative_to('/tmp'), 'use only disposable /tmp paths'
    assert re.fullmatch(r'[0-9a-f]{40}', args.sha), 'full 40-character candidate SHA required'
    assert git(checkout, 'rev-parse', 'HEAD') == args.sha, 'candidate SHA mismatch'
    assert not git(checkout, 'status', '--porcelain', '--untracked-files=all'), 'candidate checkout not clean'
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    report = output / 'junit.xml'
    here = Path(__file__).resolve().parent
    env = dict(os.environ, PYTHONPATH=str(checkout) + ':' + str(here), PATH=NODE + ':' + os.environ.get('PATH', ''))
    command = ['uv', 'run', '--no-sync', 'python', '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
               str(here / 'test_semantic_records.py'), '--junitxml', str(report)]
    lifecycle = supervise(command, checkout, env, output, secrets.token_hex(16))
    valid, error = False, None
    try:
        validate_junit(report)
        valid = True
    except (OSError, ET.ParseError, KeyError, ValueError, AssertionError) as exc:
        error = str(exc)
    try:
        unchanged = git(checkout, 'rev-parse', 'HEAD') == args.sha and not git(checkout, 'status', '--porcelain', '--untracked-files=all')
    except (OSError, subprocess.CalledProcessError):
        unchanged = False
    result = {'candidate_sha': args.sha, 'checkout': str(checkout), 'command': command,
              'lifecycle': lifecycle, 'junit_valid_two_passed_no_skip': valid, 'junit_error': error,
              'checkout_unchanged': bool(unchanged), 'claim': 'candidate-local synthetic UI/API qualification only'}
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, sort_keys=True))
    return 0 if lifecycle['primary'] == {'kind': 'exit', 'returncode': 0} and lifecycle['cleanup']['verified'] and valid and unchanged else 1


if __name__ == '__main__':
    raise SystemExit(main())
