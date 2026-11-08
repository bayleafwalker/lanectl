"""Seed: every registered adapter accepts the runner's keyword contract.
(2026-11-08: three lane-built adapters missed `env`, which carries the sandbox shim PATH.)"""
import inspect

from lanectl import adapters

RUNNER_KWARGS = {"model", "worktree", "prompt", "status_file", "timeout_s", "external", "env"}


def test_registered_adapters_accept_runner_kwargs():
    assert {"opencode", "codex", "claude"} <= set(adapters.ADAPTERS)
    for name, fn in adapters.ADAPTERS.items():
        params = inspect.signature(fn).parameters
        if any(p.kind is p.VAR_KEYWORD for p in params.values()):
            continue
        assert RUNNER_KWARGS <= set(params), (name, RUNNER_KWARGS - set(params))
