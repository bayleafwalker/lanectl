import pytest

from lanectl import coordination
from lanectl import lifecycle as view
from lanectl.cli import main


@pytest.mark.parametrize(
    ("fact", "words", "exit_code"),
    [
        ({"state": "observed", "value": {"item": {"status": "done", "resolution": "accepted"}}},
         ("done", "accepted"), 0),
        ({"state": "unknown", "reason": "unavailable"}, ("unknown",), 1),
    ],
)
def test_owner_only_terminal_reports_work_disposition(monkeypatch, capsys, fact, words, exit_code):
    monkeypatch.setattr(coordination, "_configured_client", lambda repo: object())
    monkeypatch.setattr(
        view, "lifecycle",
        lambda *args, **kwargs: {"work_id": 9, "facts": {"work.public.item-v1": fact}},
    )
    assert main(["lifecycle", "--repo", "example", "--work-id", "9"]) == exit_code
    line = next(line for line in capsys.readouterr().out.splitlines()
                if line.startswith("Work disposition:"))
    assert all(word in line for word in words)
    if exit_code:
        assert "accepted" not in line
