import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

import pytest

from lanectl.child_process import communicate


def test_cancel_terminates_descendants_before_they_can_write(tmp_path):
    marker = tmp_path / "escaped"
    script = ("import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',"
              f"{('import time,pathlib;time.sleep(.8);pathlib.Path('+repr(str(marker))+').touch()')!r}"
              "]);time.sleep(30)")
    proc = subprocess.Popen([sys.executable, "-c", script], start_new_session=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    cancelled = threading.Event()
    timer = threading.Timer(.15, cancelled.set)
    timer.start()
    before = time.monotonic()
    _, _, stopped = communicate(proc, 30, cancelled)
    assert stopped == "cancelled" and time.monotonic() - before < 3
    assert proc.poll() is not None
    time.sleep(.9)
    assert not marker.exists()


def test_normal_completion_keeps_output():
    proc = subprocess.Popen([sys.executable, "-c", "print('complete')"], start_new_session=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err, stopped = communicate(proc, 5, threading.Event())
    assert out.strip() == "complete" and not err and stopped is None


def test_named_systemd_sandbox_cancellation_stops_late_writes(tmp_path):
    from lanectl.sandbox import from_lane
    sb = from_lane({"mode": "systemd-run"}, (str(tmp_path),), 30,
                   attempt_id="cancel-proof-" + str(os.getpid()))
    marker = tmp_path / "late"
    started = tmp_path / "started"
    script = f"import pathlib,time;pathlib.Path({str(started)!r}).touch();time.sleep(2);pathlib.Path({str(marker)!r}).touch()"
    proc = subprocess.Popen([*sb.prefix(tmp_path), sys.executable, "-c", script],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + 5
    while not started.exists() and proc.poll() is None and time.monotonic() < deadline:
        time.sleep(.02)
    assert started.exists(), proc.communicate(timeout=5)
    assert sb.cancel()
    proc.communicate(timeout=5)
    time.sleep(2.1)
    assert not marker.exists()


def test_timeout_stops_sandbox_before_draining_its_inherited_pipes(tmp_path):
    from lanectl.sandbox import from_lane
    sb = from_lane({"mode": "systemd-run"}, (str(tmp_path),), 30,
                   attempt_id="timeout-proof-" + str(os.getpid()))
    marker = tmp_path / "late"
    started = tmp_path / "started"
    script = f"import pathlib,time;pathlib.Path({str(started)!r}).touch();time.sleep(2);pathlib.Path({str(marker)!r}).touch()"
    proc = subprocess.Popen([*sb.prefix(tmp_path), sys.executable, "-c", script], start_new_session=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + 5
    while not started.exists() and proc.poll() is None and time.monotonic() < deadline:
        time.sleep(.02)
    assert started.exists(), proc.communicate(timeout=5)
    before = time.monotonic()
    _, _, stopped = communicate(proc, .1, on_stop=sb.cancel)
    assert stopped == "timeout" and time.monotonic() - before < 2
    time.sleep(2.1)
    assert not marker.exists()


@pytest.mark.parametrize("cancel", [False, True])
def test_bubblewrap_worker_descendant_completion(tmp_path, cancel):
    bwrap = shutil.which("bwrap")
    bash = shutil.which("bash")
    sleep = shutil.which("sleep")
    if not all((bwrap, bash, sleep)):
        pytest.skip("requires Bubblewrap, Bash and sleep")
    bash, sleep = (Path(command).resolve() for command in (bash, sleep))
    if not all(path.is_relative_to("/nix/store") for path in (bash, sleep)):
        pytest.skip("requires the Nix-packaged appservice tools")

    # Nix coreutils can resolve sleep to a multi-call binary.
    script = (
        '((exec -a sleep "$1" .5) && printf complete > completed) & '
        'printf ready > started; wait'
    )
    proc = subprocess.Popen(
        [bwrap, "--unshare-user", "--unshare-pid", "--disable-userns",
         "--die-with-parent", "--clearenv", "--ro-bind", "/nix/store", "/nix/store",
         "--bind", str(tmp_path), "/attempt", "--dev", "/dev", "--chdir", "/attempt",
         str(bash), "-ec", script, "worker-probe", str(sleep)],
        start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )
    flag = threading.Event()
    try:
        deadline = time.monotonic() + 5
        while not (tmp_path / "started").exists() and proc.poll() is None:
            if time.monotonic() >= deadline:
                pytest.fail("Bubblewrap worker did not start")
            time.sleep(.01)
        assert (tmp_path / "started").exists(), proc.communicate(timeout=1)
        if cancel:
            flag.set()
        _, error, stopped = communicate(proc, 5, flag)
        assert stopped == ("cancelled" if cancel else None), error
        if cancel:
            time.sleep(.6)
        assert (tmp_path / "completed").exists() == (not cancel), error
    finally:
        if proc.poll() is None:
            flag.set()
            communicate(proc, 1, flag)


def test_cancel_kills_worker_even_when_sandbox_stop_raises():
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    cancelled = threading.Event()
    cancelled.set()

    def stop():
        raise RuntimeError("sandbox stop failed")

    try:
        with pytest.raises(RuntimeError, match="sandbox stop failed"):
            communicate(proc, 5, cancelled, on_stop=stop)
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=5)


def test_appservice_train_mounts_only_the_checkout(tmp_path, monkeypatch):
    from lanectl.sandbox import run_appservice_train

    tools = [shutil.which(command) for command in ("bwrap", "bash")]
    if not all(tools) or not Path(tools[1]).resolve().is_relative_to("/nix/store"):
        pytest.skip("requires the Nix-packaged appservice tools")

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    credential = tmp_path / "owner-token"
    credential.write_text("synthetic")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    result = run_appservice_train(
        checkout,
        f'test -z "${{CREDENTIALS_DIRECTORY:-}}" && test ! -e "{credential}" && printf ok > marker',
    )
    assert result.returncode == 0, result.stderr
    assert (checkout / "marker").read_text() == "ok"
    failure = run_appservice_train(checkout, "exit 41")
    assert failure.returncode == 41


def test_appservice_train_reads_linked_worktree_commit(tmp_path):
    from lanectl.sandbox import run_appservice_train

    tools = [shutil.which(command) for command in ("bwrap", "bash", "git")]
    if not all(tools) or not all(
        Path(tool).resolve().is_relative_to("/nix/store") for tool in tools[1:]
    ):
        pytest.skip("requires the Nix-packaged appservice tools")

    canonical = tmp_path / "canonical"
    train = tmp_path / "train"
    subprocess.run(["git", "init", "-q", str(canonical)], check=True)
    def git(*args):
        return subprocess.check_output(["git", "-C", str(canonical), *args], text=True).strip()

    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-q", "--allow-empty", "-m", "canonical")
    git("worktree", "add", "-q", "--detach", str(train))
    git("branch", "unrelated")
    git("tag", "unrelated")
    credential = canonical / "private"
    credential.write_text("synthetic")
    git_executable = Path(tools[-1]).resolve()
    result = run_appservice_train(
        train,
        f'test ! -e "{credential}" && '
        f'test -z "$("{git_executable}" remote)" && '
        f'test -z "$("{git_executable}" for-each-ref refs/tags refs/heads/unrelated)" && '
        f'"{git_executable}" rev-parse HEAD',
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == git("rev-parse", "HEAD")
