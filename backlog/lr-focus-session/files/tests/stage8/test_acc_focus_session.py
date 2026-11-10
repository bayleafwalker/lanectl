"""Acceptance: focus is per Claude session (planner-owned)."""
import io
import json

from lanectl import cli
from lanectl.focus import current_focus
from lanectl.usage_hook import handle_hook

ACC = "def test_ok():\n    assert True\n"


def _hook(log, tmp_path, session, mid):
    t = tmp_path / f"{session}.jsonl"
    with t.open("a") as f:
        f.write(json.dumps({"type": "assistant", "message": {
            "id": mid, "model": "claude-opus-5-5",
            "usage": {"input_tokens": 1, "output_tokens": 2}}}) + "\n")
    payload = {"session_id": session, "transcript_path": str(t), "hook_event_name": "Stop"}
    handle_hook(io.StringIO(json.dumps(payload)), log)
    return [e for e in log.read() if e["type"] == "usage.recorded"][-1]


def test_two_sessions_attribute_separately(estate, tmp_path, monkeypatch, capsys):
    _, release, log = estate
    release("aa-one", ACC)
    release("bb-two", ACC)
    monkeypatch.delenv("LANECTL_RELEASE", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-a")
    assert cli.main(["focus", "aa-one"]) == 0
    assert "focus: aa-one (planner, this session)" in capsys.readouterr().out
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-b")
    assert cli.main(["focus", "bb-two", "--role", "integrator"]) == 0
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
    a = _hook(log, tmp_path, "sess-a", "m1")
    b = _hook(log, tmp_path, "sess-b", "m2")
    c = _hook(log, tmp_path, "sess-c", "m3")
    assert (a["item_id"], a["data"]["role"]) == ("aa-one", "planner")
    assert (b["item_id"], b["data"]["role"]) == ("bb-two", "integrator")
    assert (c["item_id"], c["data"]["role"]) == (None, "interactive")


def test_without_a_session_id_global_focus_needs_a_flag(estate, tmp_path, monkeypatch, capsys):
    _, release, log = estate
    release("aa-one", ACC)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    assert cli.main(["focus", "aa-one"]) == 2
    assert "--all-sessions" in capsys.readouterr().out + capsys.readouterr().err
    assert current_focus() is None
    assert cli.main(["focus", "aa-one", "--all-sessions"]) == 0
    assert "all sessions" in capsys.readouterr().out
    assert _hook(log, tmp_path, "sess-x", "m1")["item_id"] == "aa-one"


def test_session_focus_beats_global_and_clear_is_scoped(estate, tmp_path, monkeypatch):
    _, release, log = estate
    release("aa-one", ACC)
    release("bb-two", ACC)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    assert cli.main(["focus", "aa-one", "--all-sessions"]) == 0
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-a")
    assert cli.main(["focus", "bb-two"]) == 0
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
    assert _hook(log, tmp_path, "sess-a", "m1")["item_id"] == "bb-two"
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-a")
    assert cli.main(["focus", "--clear"]) == 0
    assert current_focus("sess-a") is None and current_focus()["release_id"] == "aa-one"


def test_session_id_is_never_a_path(estate):
    assert current_focus("../../etc") is None
