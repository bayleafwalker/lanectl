"""Harness adapters. Each turns (model, worktree, prompt) into a status record.

The seed adapter delegates to `agentops dispatch run`, which already handles
OpenCode and Codex, timeouts, escalation markers and an atomic status record
(agentops-dispatch-run/v1). Further adapters register in ADAPTERS.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class AdapterResult:
    outcome: str            # done | failed | escalated
    exit_code: int
    final_tail: str
    escalation_reason: str | None
    usage: dict | None = None   # raw provider usage when the adapter can see it


def worker_for(model: str) -> str:
    if model.startswith(("opencode-go/", "opencode/")):
        return "opencode"
    if model.startswith("gpt-"):
        return "codex"
    if model.startswith("claude-"):
        return "claude"
    if model.startswith("scripted/"):
        return "scripted"   # test double; never routed in governance
    raise ValueError(f"no adapter for model {model!r}")


def agentops_dispatch(worker: str, model: str, worktree: Path, prompt: str, status_file: Path,
                      timeout_s: int, external: bool, env: dict | None = None) -> AdapterResult:
    exe = shutil.which("agentops")
    if not exe:
        raise RuntimeError("agentops CLI not on PATH")
    cmd = [exe, "dispatch", "run", "--worker", worker, "--model", model,
           "--timeout", str(timeout_s), "--worktree", str(worktree),
           "--status-file", str(status_file)]
    if external:
        cmd.append("--data-boundary-attested")
    cmd.append(prompt)
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    try:
        rec = json.loads(status_file.read_text())
    except (OSError, ValueError):
        return AdapterResult("failed", p.returncode or 1, (p.stdout + p.stderr)[-2000:], None)
    return AdapterResult(rec.get("outcome", "failed"), int(rec.get("exit_code", p.returncode)),
                         rec.get("final_message_tail") or "",
                         rec.get("escalation_reason"))


Adapter = Callable[..., AdapterResult]

ADAPTERS: dict[str, Adapter] = {
    "opencode": lambda **kw: agentops_dispatch("opencode", **kw),
    "codex": lambda **kw: agentops_dispatch("codex", **kw),
}


# Registration anchors: each adapter module registers on its own line below.
# Replace only your own anchor; leave the spacer lines so trains merge cleanly.

# @anchor opencode-native
from .adapters_opencode import run_opencode

ADAPTERS["opencode"] = run_opencode

# spacer

# @anchor claude

# spacer
