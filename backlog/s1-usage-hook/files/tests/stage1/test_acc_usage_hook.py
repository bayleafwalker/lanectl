"""Acceptance: interactive Claude Code sessions report usage (planner-owned)."""
import io
import json

from lanectl.events import EventLog
from lanectl.usage_hook import handle_hook


def _msg(mid, inp, out, cr=0, cw=0, model="claude-opus-5-5"):
    return {"type": "assistant", "message": {"id": mid, "model": model, "usage": {
        "input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": cr,
        "cache_creation_input_tokens": cw}}}


def test_hook_appends_incremental_usage_once(tmp_path):
    tr = tmp_path / "t.jsonl"
    lines = [_msg("m1", 10, 5, 100, 7), {"type": "user", "message": {"content": "hi"}},
             _msg("m1", 10, 5, 100, 7),           # streamed duplicate of the same message id
             _msg("m2", 20, 8)]
    tr.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    log = EventLog(tmp_path / "state" / "events.jsonl")
    payload = {"session_id": "sess-1", "transcript_path": str(tr), "hook_event_name": "Stop"}

    assert handle_hook(io.StringIO(json.dumps(payload)), log) == 0
    evs = [e for e in log.read() if e["type"] == "usage.recorded"]
    assert len(evs) == 1
    d = evs[0]["data"]
    assert d["provider"] == "anthropic" and d["source"] == "claude-code-interactive"
    assert d["session_id"] == "sess-1" and d["model"] == "claude-opus-5-5"
    assert d["units"] == {"input_tokens": 30, "output_tokens": 13, "cache_read_tokens": 100,
                          "cache_write_tokens": 7, "messages": 2}

    # second Stop with nothing new: no event
    handle_hook(io.StringIO(json.dumps(payload)), log)
    assert len([e for e in log.read() if e["type"] == "usage.recorded"]) == 1

    # new turn appended: only the delta is recorded
    with open(tr, "a") as fh:
        fh.write(json.dumps(_msg("m3", 1, 2)) + "\n")
    handle_hook(io.StringIO(json.dumps(payload)), log)
    evs = [e for e in log.read() if e["type"] == "usage.recorded"]
    assert len(evs) == 2 and evs[1]["data"]["units"]["input_tokens"] == 1


def test_hook_never_fails_the_session(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    assert handle_hook(io.StringIO("not json"), log) == 0
    assert handle_hook(io.StringIO(json.dumps({"session_id": "x", "transcript_path": "/nope"})), log) == 0
    assert log.read() == []


def test_cli_entrypoint_exists():
    from lanectl import cli
    import pytest
    with pytest.raises(SystemExit) as exc:
        cli.main(["hook", "usage", "--help"])
    assert exc.value.code == 0
