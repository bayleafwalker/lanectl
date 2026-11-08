"""Acceptance: headless Claude Code adapter (planner-owned)."""
import json
import os
import stat

from lanectl import adapters
from lanectl.adapters_claude import build_command, parse_result, run_claude

RESULT = {"type": "result", "subtype": "success", "is_error": False, "duration_ms": 1200,
          "num_turns": 3, "result": "Implemented.", "session_id": "s-1", "total_cost_usd": 0.0123,
          "usage": {"input_tokens": 100, "cache_creation_input_tokens": 20,
                    "cache_read_input_tokens": 300, "output_tokens": 40}}


def test_build_command_is_headless_and_scoped():
    cmd = build_command("claude-haiku-5-5", "do X")
    assert cmd[0] == "claude" and "-p" in cmd
    assert cmd[cmd.index("--model") + 1] == "claude-haiku-5-5"
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert cmd[cmd.index("--permission-mode") + 1] == "acceptEdits"
    assert "--dangerously-skip-permissions" not in cmd
    assert cmd[-1] == "do X"


def test_parse_result_usage_and_outcomes():
    out = parse_result(json.dumps(RESULT))
    assert out.outcome == "done" and out.final_tail == "Implemented."
    assert out.usage == {"input_tokens": 100, "output_tokens": 40, "cache_read_tokens": 300,
                         "cache_write_tokens": 20, "cost_usd": 0.0123, "turns": 3}
    err = parse_result(json.dumps({**RESULT, "is_error": True, "subtype": "error_max_turns"}))
    assert err.outcome == "failed"
    esc = parse_result(json.dumps({**RESULT, "result": "no\nDISPATCH_OUTCOME: ESCALATED\nESCALATION_REASON: needs schema"}))
    assert esc.outcome == "escalated" and esc.escalation_reason == "needs schema"
    assert parse_result("garbage").outcome == "failed"


def test_run_claude_with_fake_cli(tmp_path, monkeypatch):
    exe = tmp_path / "bin" / "claude"
    exe.parent.mkdir()
    exe.write_text("#!/bin/sh\npwd > \"$CLAUDE_FAKE_CWD\"\necho '" + json.dumps(RESULT) + "'\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{exe.parent}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("CLAUDE_FAKE_CWD", str(tmp_path / "cwd.txt"))
    wt = tmp_path / "wt"
    wt.mkdir()
    r = run_claude(model="claude-haiku-5-5", worktree=wt, prompt="p", status_file=tmp_path / "s.json",
                   timeout_s=10, external=False)
    assert r.outcome == "done" and r.usage["output_tokens"] == 40
    assert (tmp_path / "cwd.txt").read_text().strip() == str(wt)
    assert json.loads((tmp_path / "s.json").read_text())["outcome"] == "done"
    assert adapters.ADAPTERS["claude"] is run_claude
