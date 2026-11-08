"""Acceptance: native OpenCode adapter with usage capture (planner-owned)."""
import json
import os
import stat
from pathlib import Path

from lanectl import adapters
from lanectl.adapters_opencode import parse_stream, run_opencode

FIXTURE = Path(__file__).with_name("opencode_stream.jsonl")


def test_parse_stream_extracts_final_text_and_usage():
    final, usage = parse_stream(FIXTURE.read_text())
    assert final == "OK"
    assert usage == {"input_tokens": 8510, "output_tokens": 2, "reasoning_tokens": 0,
                     "cache_read_tokens": 1664, "cache_write_tokens": 0, "cost_usd": 0.0, "steps": 1}


def test_parse_stream_sums_steps_and_keeps_last_text_and_ignores_junk():
    lines = FIXTURE.read_text().splitlines()
    stream = "\n".join(lines + ["not json", ""] + lines).replace('"text":"OK"', '"text":"DONE"', 1)
    final, usage = parse_stream(stream)
    assert '"text":"DONE"' in stream
    assert final == "OK"                       # the last text part wins
    assert usage["input_tokens"] == 17020 and usage["steps"] == 2


def _fake_opencode(tmp_path, body):
    exe = tmp_path / "bin" / "opencode"
    exe.parent.mkdir()
    exe.write_text("#!/bin/sh\n" + body)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe.parent


def test_run_opencode_success_escalation_and_timeout(tmp_path, monkeypatch):
    escalate = '{"type":"text","part":{"type":"text","text":"cannot\\nDISPATCH_OUTCOME: ESCALATED\\nESCALATION_REASON: scope too small"}}'
    bindir = _fake_opencode(tmp_path, f"""
case "$*" in
  *ESCALATE*) echo '{escalate}' ;;
  *SLEEP*) sleep 30 ;;
  *) cat "{FIXTURE}" ;;
esac
""")
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    wt = tmp_path / "wt"
    wt.mkdir()
    kw = dict(model="opencode-go/deepseek-v4.1-flash", worktree=wt, timeout_s=5, external=True)

    ok = run_opencode(prompt="do it", status_file=tmp_path / "a.json", **kw)
    assert (ok.outcome, ok.exit_code, ok.usage["output_tokens"]) == ("done", 0, 2)
    rec = json.loads((tmp_path / "a.json").read_text())
    assert rec["outcome"] == "done" and rec["usage"]["input_tokens"] == 8510

    esc = run_opencode(prompt="ESCALATE", status_file=tmp_path / "b.json", **kw)
    assert esc.outcome == "escalated" and esc.escalation_reason == "scope too small"

    to = run_opencode(prompt="SLEEP", status_file=tmp_path / "c.json", **{**kw, "timeout_s": 1})
    assert to.outcome == "failed" and to.exit_code == 124


def test_registered_as_default_opencode_adapter():
    assert adapters.ADAPTERS["opencode"] is run_opencode
