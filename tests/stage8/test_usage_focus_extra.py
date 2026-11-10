"""Extra coverage for release focus and its use by the interactive usage hook."""
import io
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lanectl import cli
from lanectl.events import EventLog
from lanectl.focus import clear_focus, current_focus, focus_path, set_focus
from lanectl.usage_hook import handle_hook

ACC = "def test_ok():\n    assert True\n"


def _event(log, tmp_path, session="s1", mid="m1"):
    transcript = tmp_path / f"{session}.jsonl"
    with transcript.open("a") as fh:
        fh.write(json.dumps({"type": "assistant", "message": {
            "id": mid, "model": "claude-opus-5-5",
            "usage": {"input_tokens": 10, "output_tokens": 20}}}) + "\n")
    payload = {"session_id": session, "transcript_path": str(transcript),
               "hook_event_name": "Stop"}
    assert handle_hook(io.StringIO(json.dumps(payload)), log) == 0
    return [e for e in log.read() if e["type"] == "usage.recorded"][-1]


def test_focus_file_holds_release_role_and_utc_stamp(estate, tmp_path):
    _, release, _ = estate
    release("aa-work", ACC)
    assert cli.main(["focus", "aa-work"]) == 0
    raw = json.loads((Path(os.environ["LANECTL_STATE"]) / "focus.json").read_text())
    assert raw["release_id"] == "aa-work" and raw["role"] == "planner"
    set_at = datetime.strptime(raw["set_at"], "%Y-%m-%dT%H:%M:%SZ")
    assert abs((datetime.now(timezone.utc) - set_at.replace(tzinfo=timezone.utc)).total_seconds()) < 60
    assert raw == current_focus()


def test_environment_release_keeps_focus_role(estate, tmp_path, monkeypatch):
    _, release, log = estate
    release("aa-work", ACC)
    assert cli.main(["focus", "aa-work", "--role", "integrator"]) == 0
    monkeypatch.setenv("LANECTL_RELEASE", "aa-work")
    monkeypatch.delenv("LANECTL_ROLE", raising=False)
    ev = _event(log, tmp_path)
    assert ev["item_id"] == "aa-work" and ev["data"]["role"] == "integrator"


def test_environment_role_without_release_uses_focus_id(estate, tmp_path, monkeypatch):
    _, release, log = estate
    release("aa-work", ACC)
    assert cli.main(["focus", "aa-work"]) == 0
    monkeypatch.setenv("LANECTL_ROLE", " integrator ")
    monkeypatch.delenv("LANECTL_RELEASE", raising=False)
    ev = _event(log, tmp_path)
    assert ev["item_id"] == "aa-work" and ev["data"]["role"] == "integrator"


def test_blank_environment_release_falls_back_to_focus(estate, tmp_path, monkeypatch):
    _, release, log = estate
    release("aa-work", ACC)
    assert cli.main(["focus", "aa-work"]) == 0
    monkeypatch.setenv("LANECTL_RELEASE", "   ")
    monkeypatch.delenv("LANECTL_ROLE", raising=False)
    ev = _event(log, tmp_path)
    assert ev["item_id"] == "aa-work" and ev["data"]["role"] == "planner"


def test_focus_role_outside_the_vocabulary_becomes_interactive(estate, tmp_path):
    _, release, log = estate
    release("aa-work", ACC)
    set_focus("aa-work", "bogus")
    ev = _event(log, tmp_path)
    assert ev["item_id"] == "aa-work" and ev["data"]["role"] == "interactive"


def test_unreadable_focus_is_ignored(estate, tmp_path):
    _, release, log = estate
    release("aa-work", ACC)
    path = Path(os.environ["LANECTL_STATE"]) / "focus.json"
    path.write_text("{not json")
    assert current_focus() is None
    ev = _event(log, tmp_path)
    assert ev["item_id"] is None and ev["data"]["role"] == "interactive"
    path.write_text(json.dumps({"release_id": "aa-work"}))
    assert current_focus() is None


def test_unknown_release_writes_nothing(estate, capsys):
    _, release, _ = estate
    release("aa-work", ACC)
    clear_focus()
    assert cli.main(["focus", "aa-nope"]) == 2
    assert not focus_path().exists()
    assert current_focus() is None


def test_focus_stamp_just_inside_the_window_survives(estate):
    _, release, _ = estate
    release("aa-work", ACC)
    assert cli.main(["focus", "aa-work", "--role", "integrator"]) == 0
    path = Path(os.environ["LANECTL_STATE"]) / "focus.json"
    raw = json.loads(path.read_text())
    raw["set_at"] = (datetime.now(timezone.utc) - timedelta(hours=11, minutes=55)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    path.write_text(json.dumps(raw))
    assert current_focus()["release_id"] == "aa-work"
