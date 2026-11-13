"""Headless Claude Code adapter.

Claude Code's non-interactive mode prints a single JSON result object when run
with ``--output-format json``.  This module turns that object into the same
``AdapterResult`` the rest of lanectl consumes and persists a small, atomic
status record for the coordinator.

Only the Python standard library is used.  The adapter never grants Claude
Code unrestricted permissions: it always runs with ``acceptEdits`` (never
``--dangerously-skip-permissions``).
"""
from __future__ import annotations

import json
import os
import re
import signal
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # adapters imports this module at its registration anchor
    from .adapters import AdapterResult

WORKER = "claude"
SCHEMA = "lanectl-claude-adapter/v1"
TAIL_LIMIT = 2000
REASON_LIMIT = 1000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _result(outcome: str, exit_code: int, final_tail: str,
            escalation_reason: str | None, usage: dict | None = None) -> AdapterResult:
    # Deferred import: adapters.py imports this module at its registration
    # anchor, so a module-level import here would be circular.
    from .adapters import AdapterResult

    return AdapterResult(outcome, exit_code, final_tail, escalation_reason, usage)


def _verification_commands(commands):
    """Only literal, single-command rules can preserve the frozen authority."""
    verification_commands = commands
    if isinstance(verification_commands, (str, bytes)):
        raise ValueError("verification commands must be a sequence")
    try:
        verification_commands = tuple(verification_commands)
    except TypeError:
        raise ValueError("verification commands must be a sequence") from None
    for check in verification_commands:
        if (not isinstance(check, str) or not check.strip()
                or any(char in check for char in "*\r\n\0,&|;")):
            raise ValueError("verification command cannot be represented as an exact permission rule")
    return verification_commands


def build_command(model: str, prompt: str, *, verification_commands=()) -> list[str]:
    """Build headless argv with exact rules, never unrestricted Bash."""
    command = ["claude", "-p", "--model", model, "--output-format", "json",
               "--permission-mode", "acceptEdits"]
    rules = [f"Bash({check})" for check in _verification_commands(verification_commands)]
    if rules:
        command += ["--allowedTools", *rules, "--"]
    return command + [prompt]


def _result_object(stdout: str) -> dict | None:
    """Return the result object from stdout, tolerating surrounding noise."""
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
    except (TypeError, ValueError):
        obj = None
    if isinstance(obj, dict):
        return obj

    # A CLI may emit log lines before or after the result, or pretty-print the
    # object over several lines.  Scan for the first decodable object that
    # looks like a Claude result.
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(text[index:])
        except ValueError:
            continue
        if isinstance(candidate, dict) and ("result" in candidate or candidate.get("type") == "result"):
            return candidate
    return None


def _escalation(text: str) -> tuple[bool, str | None]:
    """Detect the dispatch escalation marker in final result text.

    Formatting added by the model (markdown emphasis, blockquote/list markers,
    heading hashes) is ignored so the marker is not missed in a styled answer.
    """
    lines = []
    for raw in (text or "").splitlines():
        line = re.sub(r"[*`]", "", raw).strip().lstrip("#").strip()
        line = re.sub(r"^_+|_+$", "", line)
        lines.append(line)
    marker = any(
        re.fullmatch(r"[-+> ]*DISPATCH_OUTCOME\s*:\s*ESCALATED[.,;:!? ]*", line, re.IGNORECASE)
        for line in lines
    )
    reason = None
    for line in lines:
        match = re.fullmatch(
            r"[-+> ]*ESCALATION_REASON\s*:\s*(.+?)\s*[.,;:!? ]*", line, re.IGNORECASE
        )
        if match:
            reason = match.group(1).strip(" .,;:!?")[:REASON_LIMIT]
            break
    return marker, reason


def _usage(raw: object, cost: object, turns: object) -> dict:
    usage = raw if isinstance(raw, dict) else {}

    def count(key: str) -> int:
        value = usage.get(key)
        return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0

    try:
        cost_usd = float(cost) if cost is not None else 0.0
    except (TypeError, ValueError):
        cost_usd = 0.0
    try:
        num_turns = int(turns) if turns is not None else 0
    except (TypeError, ValueError):
        num_turns = 0
    return {
        "input_tokens": count("input_tokens"),
        "output_tokens": count("output_tokens"),
        "cache_read_tokens": count("cache_read_input_tokens"),
        "cache_write_tokens": count("cache_creation_input_tokens"),
        "cost_usd": cost_usd,
        "turns": num_turns,
    }


def parse_result(stdout: str) -> AdapterResult:
    """Parse Claude Code's single JSON result object into an AdapterResult."""
    obj = _result_object(stdout)
    if obj is None:
        return _result("failed", 1, (stdout or "")[-TAIL_LIMIT:], None)

    text = obj.get("result")
    text = text if isinstance(text, str) else ""
    escalated, reason = _escalation(text)
    if obj.get("permission_denials") and not escalated:
        escalated, reason = True, "native permission denial prevented autonomous verification"
    if escalated:
        outcome = "escalated"
    elif obj.get("is_error"):
        outcome = "failed"
    else:
        outcome = "done"

    usage = _usage(obj.get("usage"), obj.get("total_cost_usd"), obj.get("num_turns"))
    exit_code = 1 if outcome == "failed" else 0
    return _result(outcome, exit_code, text[-TAIL_LIMIT:],
                   reason if escalated else None, usage)


def _write_status(path: Path, record: dict) -> None:
    """Write a status record atomically (same directory, fsync, replace)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _record(outcome: str, exit_code: int, final_tail: str, reason: str | None,
            usage: dict | None, *, model: str, worktree: Path, external: bool,
            started_at: str, ended_at: str) -> dict:
    return {
        "schema": SCHEMA,
        "outcome": outcome,
        "exit_code": exit_code,
        "worker": WORKER,
        "model": model,
        "external": bool(external),
        "final_message_tail": (final_tail or "")[-TAIL_LIMIT:],
        "escalation_reason": reason,
        "usage": usage,
        "worktree": str(worktree),
        "started_at": started_at,
        "ended_at": ended_at,
    }


def _run_child(cmd: list[str], worktree: Path, timeout_s: float,
               env: dict | None = None, cancel_event=None, stop_callback=None) -> tuple[str, str, int, bool]:
    """Run the CLI in its own process group so a timeout kills descendants."""
    proc = subprocess.Popen(
        cmd,
        cwd=str(worktree),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env=env,
    )
    if cancel_event is not None or stop_callback is not None:
        from .child_process import communicate
        stdout, stderr, stopped = communicate(proc, timeout_s, cancel_event, on_stop=stop_callback)
        return stdout or "", stderr or "", 130 if stopped == "cancelled" else 124 if stopped else proc.returncode, bool(stopped)
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
        return stdout, stderr, proc.returncode, False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        stdout, stderr = proc.communicate()
        return stdout or "", stderr or "", 124, True


def run_claude(*, model: str, worktree: Path, prompt: str, status_file: Path,
               timeout_s: float, external: bool, env: dict | None = None, cancel_event=None, stop_callback=None,
               verification_commands=()) -> AdapterResult:
    """Run Claude Code headless and return a normalised result.

    A timeout is recorded as ``failed`` with exit code 124.  The status file is
    written atomically both before launch (``running``) and at completion.
    """
    worktree = Path(worktree)
    status_file = Path(status_file)
    started_at = _now()
    _write_status(status_file, {
        "schema": SCHEMA, "outcome": "running", "exit_code": None, "worker": WORKER,
        "model": model, "external": bool(external), "final_message_tail": "",
        "escalation_reason": None, "usage": None, "worktree": str(worktree),
        "started_at": started_at, "ended_at": None,
    })

    exe = shutil.which(WORKER, path=(env or os.environ).get("PATH"))   # honour sandbox shims
    if not exe:
        result = _result("failed", 127, "claude CLI not found on PATH", None)
        _write_status(status_file, _record(
            result.outcome, result.exit_code, result.final_tail, None, None,
            model=model, worktree=worktree, external=external,
            started_at=started_at, ended_at=_now()))
        return result

    try:
        checks = _verification_commands(verification_commands)
        if checks:
            prompt += ("\n\n# Native verification\nRun these declared checks verbatim; "
                       "no additional Bash commands are authorized by this profile:\n"
                       + "\n".join("- " + check for check in checks))
        cmd = build_command(model, prompt, verification_commands=checks)
        cmd[0] = exe
        kwargs = {"cancel_event": cancel_event} if cancel_event is not None else {}
        if stop_callback is not None:
            kwargs["stop_callback"] = stop_callback
        stdout, stderr, exit_code, timed_out = _run_child(cmd, worktree, timeout_s, env, **kwargs)
    except (OSError, ValueError) as exc:
        result = _result("failed", 1, f"claude launch failed: {exc}", None)
        _write_status(status_file, _record(
            result.outcome, result.exit_code, result.final_tail, None, None,
            model=model, worktree=worktree, external=external,
            started_at=started_at, ended_at=_now()))
        return result

    if timed_out:
        detail = "claude timed out after %ss" % timeout_s
        partial = (stdout + stderr).strip()
        final = f"{detail}\n{partial}" if partial else detail
        result = _result("failed", 124, final[-TAIL_LIMIT:], None)
        if cancel_event is not None and cancel_event.is_set():
            result = _result("failed", 130, "native execution cancelled after lease loss", None)
    else:
        parsed = parse_result(stdout)
        tail = parsed.final_tail or (stdout + stderr)[-TAIL_LIMIT:]
        if parsed.outcome == "done" and exit_code != 0:
            result = _result("failed", exit_code, tail, None, parsed.usage)
        elif parsed.outcome == "failed" and exit_code == 0:
            result = _result("failed", 1, tail, None, parsed.usage)
        else:
            result = _result(parsed.outcome, exit_code, tail,
                             parsed.escalation_reason, parsed.usage)

    _write_status(status_file, _record(
        result.outcome, result.exit_code, result.final_tail,
        result.escalation_reason, result.usage,
        model=model, worktree=worktree, external=external,
        started_at=started_at, ended_at=_now()))
    return result
