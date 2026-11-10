"""Bound native worker execution and cancel its entire process group."""
import os
import signal
import subprocess
import time


def communicate(proc, timeout_s, cancel_event=None):
    deadline = time.monotonic() + timeout_s
    while True:
        stopped = ("cancelled" if cancel_event is not None and cancel_event.is_set()
                   else "timeout" if time.monotonic() >= deadline else None)
        if stopped:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, err = proc.communicate(timeout=10)
            return out, err, stopped
        try:
            out, err = proc.communicate(timeout=min(.1, max(.001, deadline - time.monotonic())))
            return out, err, None
        except subprocess.TimeoutExpired:
            continue
