"""Acceptance: interactive usage is attributed to a release (planner-owned)."""
import io
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lanectl import cli
from lanectl.focus import current_focus
from lanectl.usage_hook import handle_hook

ACC = "def test_ok():\n    assert True\n"


def _turn(tmp_path, mid):
    t = tmp_path / "transcript.jsonl"
    with t.open("a") as f:
        f.write(json.dumps({"type": "assistant", "message": {
            "id": mid, "model": "claude-opus-5-5",
            "usage": {"input_tokens": 10, "output_tokens": 20}}}) + "\n")
    return t


def _hook(log, transcript):
    payload = {"session_id": "s1", "transcript_path": str(transcript), "hook_event_name": "Stop"}
    assert handle_hook(io.StringIO(json.dumps(payload)), log) == 0
    return [e for e in log.read() if e["type"] == "usage.recorded"][-1]


def test_focus_attributes_session_usage(estate, tmp_path, capsys):
    _, release, log = estate
    release("aa-work", ACC)
    assert cli.main(["focus", "aa-work", "--role", "integrator"]) == 0
    assert "focus: aa-work (integrator)" in capsys.readouterr().out
    ev = _hook(log, _turn(tmp_path, "m1"))
    assert ev["item_id"] == "aa-work" and ev["data"]["role"] == "integrator"
    assert cli.main(["focus"]) == 0
    assert "focus: aa-work (integrator)" in capsys.readouterr().out


def test_clear_and_unfocused_usage(estate, tmp_path, capsys):
    _, release, log = estate
    release("aa-work", ACC)
    assert cli.main(["focus", "aa-work"]) == 0
    assert current_focus()["role"] == "planner"
    assert cli.main(["focus", "--clear"]) == 0
    assert current_focus() is None
    ev = _hook(log, _turn(tmp_path, "m1"))
    assert ev["item_id"] is None and ev["data"]["role"] == "interactive"
    capsys.readouterr()
    assert cli.main(["focus"]) == 0
    assert "no focus" in capsys.readouterr().out


def test_unknown_release_is_refused(estate, capsys):
    assert cli.main(["focus", "nope"]) == 2
    assert current_focus() is None


def test_environment_overrides_focus(estate, tmp_path, monkeypatch):
    _, release, log = estate
    release("aa-work", ACC)
    release("bb-other", ACC)
    assert cli.main(["focus", "aa-work"]) == 0
    monkeypatch.setenv("LANECTL_RELEASE", " bb-other ")
    monkeypatch.setenv("LANECTL_ROLE", "bogus")
    ev = _hook(log, _turn(tmp_path, "m1"))
    assert ev["item_id"] == "bb-other" and ev["data"]["role"] == "interactive"


def test_stale_focus_is_ignored(estate, tmp_path):
    _, release, log = estate
    release("aa-work", ACC)
    assert cli.main(["focus", "aa-work"]) == 0
    path = Path(os.environ["LANECTL_STATE"]) / "focus.json"
    raw = json.loads(path.read_text())
    old = datetime.now(timezone.utc) - timedelta(hours=13)
    raw["set_at"] = old.strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(json.dumps(raw))
    assert current_focus() is None
    assert _hook(log, _turn(tmp_path, "m1"))["item_id"] is None
