import os
import subprocess
import sys
import threading
import time

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
