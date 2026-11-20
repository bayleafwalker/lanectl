"""Native OpenCode adapter.

Runs ``opencode run --format json`` in the attempt worktree, parses its JSON
event stream (text parts and ``step_finish`` token/cost data), and returns an
:class:`~lanectl.adapters.AdapterResult` carrying the usage the runner records
as a ``usage.recorded`` event.

The CLI is expected on ``PATH``. A timeout kills the whole process group so
child tool processes cannot outlive the attempt.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .adapters import AdapterResult

_ESCALATED = re.compile(r"DISPATCH_OUTCOME:\s*ESCALATED\b")
_ESCALATION_REASON = re.compile(r"ESCALATION_REASON:\s*(.+)")


def _empty_usage() -> dict:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_usd": 0.0,
        "steps": 0,
    }


def parse_stream(text: str) -> tuple[str, dict]:
    """Parse an OpenCode JSONL stream into (last text part, summed usage).

    Unknown lines, blank lines and non-object events are ignored. Text parts
    are collected in order; the last one is the worker's final message. Every
    ``step_finish`` adds its token counts and cost to the usage totals.
    """
    final_text = ""
    usage = _empty_usage()
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (TypeError, ValueError):
            continue
        if not isinstance(event, dict):
            continue
        part = event.get("part")
        if not isinstance(part, dict):
            continue
        etype = event.get("type") or part.get("type")
        if etype == "text":
            value = part.get("text")
            if isinstance(value, str):
                final_text = value
        elif etype == "step_finish":
            tokens = part.get("tokens")
            if not isinstance(tokens, dict):
                tokens = {}
            cache = tokens.get("cache")
            if not isinstance(cache, dict):
                cache = {}
            usage["input_tokens"] += int(tokens.get("input") or 0)
            usage["output_tokens"] += int(tokens.get("output") or 0)
            usage["reasoning_tokens"] += int(tokens.get("reasoning") or 0)
            usage["cache_read_tokens"] += int(cache.get("read") or 0)
            usage["cache_write_tokens"] += int(cache.get("write") or 0)
            usage["cost_usd"] += float(part.get("cost") or 0.0)
            usage["steps"] += 1
    return final_text, usage


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_status(status_file: Path, record: dict) -> None:
    """Atomically replace ``status_file`` with ``record``."""
    path = Path(status_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(record, fh, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _marker_text(output: str) -> str:
    """All text parts joined, so markers split across steps are still seen."""
    texts = []
    for raw in (output or "").splitlines():
        try:
            event = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(event, dict) or event.get("type") != "text":
            continue
        part = event.get("part")
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            texts.append(part["text"])
    return "\n".join(texts)


def run_opencode(*, model: str, worktree: Path, prompt: str, status_file: Path,
                 timeout_s: int, external: bool, env: dict | None = None, cancel_event=None, stop_callback=None) -> AdapterResult:
    """Run OpenCode once and return its outcome, usage and escalation state."""
    started = _utcnow()
    cmd = ["opencode", "run", "--format", "json", "--model", model, "--", prompt]
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(worktree), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, start_new_session=True, env=env,
        )
    except OSError as exc:
        return _record_result("", 127, started, model, status_file,
                              diagnostic=f"opencode launch error: {exc}")

    timed_out = False
    try:
        if cancel_event is not None or stop_callback is not None:
            from .child_process import communicate
            output, _, stopped = communicate(proc, timeout_s, cancel_event, on_stop=stop_callback)
            timed_out = bool(stopped)
        else:
            output, _ = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            output, _ = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            output, _ = proc.communicate()

    code = proc.returncode
    if timed_out:
        code = 130 if cancel_event is not None and cancel_event.is_set() else 124
    return _record_result(output, code, started, model, status_file, interrupted=timed_out)


def run_appservice_opencode(*, model: str, worktree: Path, prompt: str, status_file: Path,
                            timeout_s: int, config: Path, cancel_event=None) -> AdapterResult:
    """Run the image's OpenCode executable through the appservice boundary."""
    from .sandbox import run_appservice_command

    started = _utcnow()
    executable = shutil.which("opencode")
    if executable is None:
        return _record_result("", 127, started, model, status_file, diagnostic="OpenCode is missing")
    argv = [executable, "run", "--standalone", "--format", "json", "--model", model, "--", prompt]
    try:
        process = run_appservice_command(worktree, argv, timeout_s, cancel_event=cancel_event,
                                         opencode_config=config)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        return _record_result("", 125, started, model, status_file, diagnostic=type(exc).__name__)
    return _record_result(process.stdout, process.returncode, started, model, status_file,
                          interrupted=process.returncode in (124, 125, 130), diagnostic=process.stderr)


def _record_result(output, exit_code, started, model, status_file, *, interrupted=False, diagnostic=""):
    from .adapters import AdapterResult

    output = output or ""
    final_text, usage = parse_stream(output)
    if interrupted:
        outcome, reason = "failed", None
    else:
        marker_text = _marker_text(output)
        if _ESCALATED.search(marker_text):
            outcome = "escalated"
            reason_match = _ESCALATION_REASON.search(marker_text)
            reason = reason_match.group(1).strip() if reason_match else None
        elif exit_code == 0:
            outcome, reason = "done", None
        else:
            outcome, reason = "failed", None

    tail = (final_text or diagnostic)[-2000:]
    ended = _utcnow()
    _write_status(status_file, {
        "outcome": outcome, "exit_code": exit_code, "usage": usage, "model": model,
        "started": started, "ended": ended, "final_message_tail": tail,
        "escalation_reason": reason,
    })
    return AdapterResult(outcome, exit_code, tail, reason, usage)
