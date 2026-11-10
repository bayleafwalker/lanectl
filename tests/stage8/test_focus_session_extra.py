"""Extra coverage: focus is per session, and a session id is never a path.

These exercise the ``session_id`` parameter directly; they fail against the
machine-wide-only ``focus`` API and pass once focus is per Claude session.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lanectl.focus import clear_focus, current_focus, set_focus


def test_session_focus_and_machine_focus_are_independent(estate):
    set_focus("aa-one", "planner", "sess-a")
    set_focus("bb-two", "integrator")
    assert current_focus("sess-a")["release_id"] == "aa-one"
    assert current_focus("sess-a")["role"] == "planner"
    assert current_focus()["release_id"] == "bb-two"
    assert current_focus()["role"] == "integrator"


def test_invalid_session_id_is_absent_never_a_path(estate):
    set_focus("aa-one", "planner", "../../etc")
    assert current_focus("../../etc") is None
    clear_focus("../../etc")  # no error, and nothing is written anywhere
    state = Path(os.environ["LANECTL_STATE"])
    assert not (state / "focus.json").exists()
    assert not (state / "focus").exists()


def test_clear_scopes_to_the_session(estate):
    set_focus("aa-one", "planner", "sess-a")
    set_focus("bb-two", "integrator")
    clear_focus("sess-a")
    assert current_focus("sess-a") is None
    assert current_focus()["release_id"] == "bb-two"


def test_stale_session_focus_is_ignored_independently(estate):
    set_focus("aa-one", "planner", "sess-a")
    set_focus("bb-two", "integrator")
    path = Path(os.environ["LANECTL_STATE"]) / "focus" / "sess-a.json"
    raw = json.loads(path.read_text())
    raw["set_at"] = (datetime.now(timezone.utc) - timedelta(hours=13)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    path.write_text(json.dumps(raw))
    assert current_focus("sess-a") is None
    assert current_focus()["release_id"] == "bb-two"
