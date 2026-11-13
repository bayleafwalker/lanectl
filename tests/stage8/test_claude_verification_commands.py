"""A headless worker can execute its exact planner-declared falsifier."""
from dataclasses import replace
import json

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


@pytest.mark.parametrize("has_snip", [False, True])
@pytest.mark.parametrize("prefix", ["", "snip proxy -- "])
def test_native_launch_preserves_the_exact_declared_command(tmp_path, monkeypatch, has_snip, prefix):
    monkeypatch.setattr(claude.shutil, "which", lambda name, **kw: "/trusted/"+name if name=="claude" or has_snip else None)
    seen = []
    def child(cmd, *args, **kwargs):
        seen.append(cmd)
        return json.dumps({"result":"synthetic completed verification","is_error":False}), "", 0, False
    monkeypatch.setattr(claude, "_run_child", child)
    check = prefix + "uv run --no-sync pytest -q tests/proof.py"
    result = claude.run_claude(model="claude-sonnet-5-5",worktree=tmp_path,prompt="bounded task",
        status_file=tmp_path/"status.json",timeout_s=30,external=False,
        env={"PATH":"/trusted"},verification_commands=(check,))
    assert result.outcome == "done"
    cmd = seen[0]
    assert cmd[cmd.index("--allowedTools")+1] == "Bash("+check+")"
    assert check in cmd[-1] and "verbatim" in cmd[-1]
    assert "Bash" not in cmd and "Bash(*)" not in cmd


def test_native_permission_denials_cannot_report_a_completed_attempt():
    parsed = claude.parse_result(json.dumps({"result":"done", "is_error":False,
        "permission_denials":[{"tool_name":"Bash","tool_input":{"command":"private-command-sentinel"}}]}))
    assert parsed.outcome == "escalated" and "permission" in parsed.escalation_reason
    assert "private-command-sentinel" not in parsed.escalation_reason
    assert claude.parse_result(json.dumps({"result":"done","permission_denials":[]})).outcome == "done"
