"""Real child/process-group cancellation and failed-startup controls, no app mocks in acceptance."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

RUNNER = Path(__file__).resolve().parent / "run-dashboard.sh"


def alive(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[2] not in {"Z", "X"}
    except FileNotFoundError:
        return False


with tempfile.TemporaryDirectory(prefix="currency-lifecycle-") as folder:
    root = Path(folder)
    (root / "tools").mkdir()
    (root / "tools/project-env.sh").write_text(":\n")
    (root / ".venv/bin").mkdir(parents=True)
    (root / ".venv/bin/python").symlink_to(sys.executable)
    (root / "tests").mkdir()
    (root / "apps/web/frontend").mkdir(parents=True)
    fakebin = root / "bin"
    fakebin.mkdir()
    (fakebin / "curl").write_text("#!/bin/sh\nif [ \"${CONTROL_FAIL:-0}\" = 1 ]; then sleep .3; exit 1; fi\nexit 0\n")
    (fakebin / "curl").chmod(0o755)
    child_program = "import signal,time,pathlib,sys; signal.signal(signal.SIGTERM,signal.SIG_IGN); pathlib.Path(sys.argv[1]).write_text('ready'); time.sleep(120)"
    leader = '''import os, pathlib, signal, subprocess, sys, time
root=pathlib.Path(os.environ['CONTROL_ROOT'])
role=sys.argv[1]
signal.signal(signal.SIGTERM, signal.SIG_IGN)
child=subprocess.Popen([sys.executable, '-c', %r, str(root / (role + '.ready'))], start_new_session=False)
while not (root / (role + '.ready')).exists(): time.sleep(.01)
(root / (role + '.pid')).write_text(str(os.getpid()) + ' ' + str(child.pid))
if role == 'web' and os.environ.get('CONTROL_FAIL') == '1': sys.exit(1)
time.sleep(120)
''' % child_program
    (root / "tests/currency_dashboard_fixture.py").write_text(leader.replace("role=sys.argv[1]", "role='backend'"))
    (fakebin / "node").write_text("#!" + sys.executable + "\n" + leader.replace("role=sys.argv[1]", "role='runner' if 'playwright/test/cli.js' in sys.argv[1] else 'web'"))
    (fakebin / "node").chmod(0o755)
    for mode, sig, expected in [("term", signal.SIGTERM, 143), ("int", signal.SIGINT, 130), ("failure", None, 1)]:
        if len(sys.argv) > 1 and mode != sys.argv[1]: continue
        for role in ('backend', 'web', 'runner'):
            (root / (role + '.pid')).unlink(missing_ok=True)
            (root / (role + '.ready')).unlink(missing_ok=True)
        env = dict(os.environ, PATH=f"{fakebin}:{os.environ['PATH']}", CONTROL_ROOT=str(root),
                   CURRENCY_ACCEPTANCE_POSTGRES_DSN="synthetic", CURRENCY_ACCEPTANCE_HTTP_PORT="0",
                   CURRENCY_ACCEPTANCE_WEB_PORT="0", CURRENCY_ACCEPTANCE_UI_REPORT=str(root / (mode + '.json')))
        if mode == 'failure': env['CONTROL_FAIL'] = '1'
        manager = subprocess.Popen(['bash', str(RUNNER)], cwd=root, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            deadline=time.monotonic()+8
            needed=('backend','web') if mode == 'failure' else ('backend','web','runner')
            while time.monotonic()<deadline and not all((root/(r+'.pid')).exists() for r in needed):
                if manager.poll() is not None: break
                time.sleep(.02)
            assert all((root/(r+'.pid')).exists() for r in needed), (mode, manager.poll(), manager.communicate(timeout=2) if manager.poll() is not None else '')
            pids=[int(x) for r in needed for x in (root/(r+'.pid')).read_text().split()]
            start=time.monotonic()
            if sig: os.kill(manager.pid, sig)
            try:
                out, err=manager.communicate(timeout=20)
            except subprocess.TimeoutExpired:
                print('timeout', mode, 'manager poll', manager.poll(), 'pids', [(pid, alive(pid)) for pid in pids], flush=True)
                raise
            assert manager.returncode == expected, (mode,manager.returncode,out,err)
            assert time.monotonic()-start < 20
            assert not any(alive(pid) for pid in pids), (mode,pids)
            assert not (root/(mode+'.json')).exists()
            print(mode, 'exit', manager.returncode, 'owned leaders and TERM-ignoring same-group descendants settled')
        finally:
            if manager.poll() is None:
                os.killpg(manager.pid, signal.SIGKILL)
                manager.wait(timeout=3)
            for role in ('backend', 'web', 'runner'):
                pidfile = root / (role + '.pid')
                if pidfile.exists():
                    for pid in map(int, pidfile.read_text().split()):
                        try:
                            pgid = os.getpgid(pid)
                            if pgid != os.getpgrp():
                                os.killpg(pgid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass

    fake_ps = fakebin / 'ps'
    fake_ps.write_text('#!/bin/sh\nprintf "424242 S\\n"\n')
    fake_ps.chmod(0o755)
    helper = Path(__file__).resolve().parent / 'process-groups.sh'
    result = subprocess.run(['bash', '-c', 'source "$1"; kill() { return 1; }; dev_stop_process_group 424242 1 1 0', '_', str(helper)],
                            env=dict(os.environ, PATH=f'{fakebin}:{os.environ["PATH"]}'),
                            capture_output=True, text=True, timeout=3)
    assert result.returncode != 0 and 'did not settle' in result.stderr, result.stderr
    print('unsettled group rejected with nonzero status')
