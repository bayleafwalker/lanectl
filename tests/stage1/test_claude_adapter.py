"""Unit tests for the headless Claude Code adapter (worker-owned)."""
import json
import os
import stat
import subprocess
import sys
import time

from lanectl import adapters
from lanectl.adapters_claude import build_command, parse_result, run_claude

RESULT = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "duration_ms": 1200,
    "num_turns": 3,
    "result": "Implemented.",
    "session_id": "s-1",
    "total_cost_usd": 0.0123,
    "usage": {
        "input_tokens": 100,
        "cache_creation_input_tokens": 20,
        "cache_read_input_tokens": 300,
        "output_tokens": 40,
    },
}


def _fake_claude(tmp_path, body):
    exe = tmp_path / "bin" / "claude"
    exe.parent.mkdir(exist_ok=True)
    exe.write_text("#!/bin/sh\n" + body)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe.parent


def _env(tmp_path, monkeypatch, bindir):
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("CLAUDE_FAKE_CWD", str(tmp_path / "cwd.txt"))


def test_build_command_is_exactly_headless_and_never_unrestricted():
    cmd = build_command("claude-haiku-5-5", "do X")
    assert cmd == ["claude", "-p", "--model", "claude-haiku-5-5", "--output-format", "json",
                   "--permission-mode", "acceptEdits", "do X"]
    assert "--dangerously-skip-permissions" not in cmd


def test_parse_result_handles_noise_markdown_and_partial_usage():
    noisy = "log line\n" + json.dumps(RESULT, indent=2) + "\ntrailing noise\n"
    assert parse_result(noisy).outcome == "done"

    styled = {**RESULT, "result": "**DISPATCH_OUTCOME: ESCALATED**\n"
                                      "`ESCALATION_REASON: needs a schema`"}
    escalated = parse_result(json.dumps(styled))
    assert (escalated.outcome, escalated.escalation_reason) == ("escalated", "needs a schema")

    partial = parse_result(json.dumps({"result": "ok", "is_error": False}))
    assert partial.outcome == "done"
    assert partial.usage == {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
                             "cache_write_tokens": 0, "cost_usd": 0.0, "turns": 0}


def test_run_claude_writes_status_and_normalises_usage(tmp_path, monkeypatch):
    bindir = _fake_claude(tmp_path, 'pwd > "$CLAUDE_FAKE_CWD"\necho \'%s\'\n' % json.dumps(RESULT))
    _env(tmp_path, monkeypatch, bindir)
    wt = tmp_path / "wt"
    wt.mkdir()
    status = tmp_path / "runs" / "s.json"

    result = run_claude(model="claude-haiku-5-5", worktree=wt, prompt="p", status_file=status,
                        timeout_s=10, external=True)

    assert (result.outcome, result.exit_code) == ("done", 0)
    assert result.usage == {"input_tokens": 100, "output_tokens": 40, "cache_read_tokens": 300,
                            "cache_write_tokens": 20, "cost_usd": 0.0123, "turns": 3}
    assert (tmp_path / "cwd.txt").read_text().strip() == str(wt)
    record = json.loads(status.read_text())
    assert record["outcome"] == "done" and record["exit_code"] == 0
    assert record["usage"]["cost_usd"] == 0.0123 and record["external"] is True
    assert record["worker"] == "claude" and record["model"] == "claude-haiku-5-5"
    assert record["final_message_tail"] == "Implemented."
    assert sorted(p.name for p in status.parent.iterdir()) == ["s.json"]


def test_run_claude_escalates_even_when_the_cli_exits_nonzero(tmp_path, monkeypatch):
    payload = {**RESULT, "is_error": True,
               "result": "blocked\nDISPATCH_OUTCOME: ESCALATED\nESCALATION_REASON: needs a schema"}
    bindir = _fake_claude(tmp_path, "echo '%s'\nexit 7\n" % json.dumps(payload))
    _env(tmp_path, monkeypatch, bindir)
    wt = tmp_path / "wt"
    wt.mkdir()

    result = run_claude(model="claude-haiku-5-5", worktree=wt, prompt="p",
                        status_file=tmp_path / "s.json", timeout_s=10, external=False)

    assert result.outcome == "escalated"
    assert result.escalation_reason == "needs a schema"
    record = json.loads((tmp_path / "s.json").read_text())
    assert (record["outcome"], record["escalation_reason"]) == ("escalated", "needs a schema")


def test_run_claude_timeout_kills_the_worker_and_records_124(tmp_path, monkeypatch):
    bindir = _fake_claude(tmp_path, "sleep 30\n")
    _env(tmp_path, monkeypatch, bindir)
    wt = tmp_path / "wt"
    wt.mkdir()

    started = time.monotonic()
    result = run_claude(model="claude-haiku-5-5", worktree=wt, prompt="p",
                        status_file=tmp_path / "s.json", timeout_s=1, external=False)
    elapsed = time.monotonic() - started

    assert (result.outcome, result.exit_code) == ("failed", 124)
    assert elapsed < 10
    record = json.loads((tmp_path / "s.json").read_text())
    assert (record["outcome"], record["exit_code"]) == ("failed", 124)
    assert "timed out" in record["final_message_tail"]


def test_run_claude_missing_cli_and_bad_output_fail_with_records(tmp_path, monkeypatch):
    bindir = tmp_path / "empty"
    bindir.mkdir()
    monkeypatch.setenv("PATH", str(bindir))
    wt = tmp_path / "wt"
    wt.mkdir()

    missing = run_claude(model="claude-haiku-5-5", worktree=wt, prompt="p",
                         status_file=tmp_path / "missing.json", timeout_s=5, external=False)
    assert (missing.outcome, missing.exit_code) == ("failed", 127)
    assert json.loads((tmp_path / "missing.json").read_text())["exit_code"] == 127

    garbage = _fake_claude(tmp_path, "echo not-json\nexit 0\n")
    _env(tmp_path, monkeypatch, garbage)
    bad = run_claude(model="claude-haiku-5-5", worktree=wt, prompt="p",
                     status_file=tmp_path / "bad.json", timeout_s=5, external=False)
    assert (bad.outcome, bad.exit_code) == ("failed", 1)
    assert json.loads((tmp_path / "bad.json").read_text())["outcome"] == "failed"


def test_registered_as_claude_adapter():
    assert adapters.ADAPTERS["claude"] is run_claude


def test_module_imports_standalone_without_circular_import():
    check = subprocess.run(
        [sys.executable, "-c", "import lanectl.adapters_claude as m; print(m.WORKER)"],
        capture_output=True, text=True,
    )
    assert check.returncode == 0, check.stderr
    assert check.stdout.strip() == "claude"
