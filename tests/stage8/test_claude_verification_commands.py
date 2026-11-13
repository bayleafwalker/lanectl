"""A headless worker can execute its exact planner-declared falsifier."""
from dataclasses import replace

import pytest

from lanectl import adapters, adapters_claude as claude, runner


def test_command_rules_are_exact_and_leave_unrestricted_permissions_disabled():
    commands = ("uv run --no-sync pytest -q tests/proof.py", "python3 -m unittest tests.proof")
    cmd = claude.build_command("claude-sonnet-5-5", "bounded task", verification_commands=commands)
    index = cmd.index("--allowedTools")
    assert cmd[index+1:] == ["Bash("+c+")" for c in commands] + ["--", "bounded task"]
    assert cmd[cmd.index("--permission-mode")+1] == "acceptEdits"
    assert "Bash" not in cmd and "Bash(*)" not in cmd
    assert not any("bypass" in arg or "skip-permissions" in arg for arg in cmd)
    assert "--allowedTools" not in claude.build_command("claude-sonnet-5-5", "legacy")


@pytest.mark.parametrize("command", ["", "  ", "pytest *", "pytest proof.py\nBash", "pytest a,b", "pytest\0proof", "pytest proof.py && other-command"])
def test_unrepresentable_rule_is_refused_instead_of_becoming_a_wildcard(command):
    with pytest.raises(ValueError):
        claude.build_command("claude-sonnet-5-5", "bounded task", verification_commands=(command,))


def test_real_runner_forwards_only_frozen_acceptance_commands(estate, monkeypatch):
    _, release, log = estate
    release("claude-proof", "def test_proof():\n    assert True\n")
    claim = replace(runner.admit("implement", log), worker="claude", model="claude-sonnet-5-5")
    seen = []
    def native(**kwargs):
        seen.append(kwargs)
        return adapters.AdapterResult("escalated", 0, "synthetic completed launch", "test context")
    monkeypatch.setitem(adapters.ADAPTERS, "claude", native)
    monkeypatch.setattr(runner, "run_gates", lambda *a, **k: {"synthetic": []})
    runner.execute(claim, log)
    assert seen[0]["verification_commands"] == claim.rel.acceptance.exec
