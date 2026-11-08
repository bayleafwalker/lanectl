"""Extra coverage: events --type composes with --item and -n."""
import json

from lanectl import cli
from lanectl.events import EventLog


def _types(out):
    return [json.loads(line)["type"] for line in out.splitlines()]


def test_events_type_filter_combines_with_item_and_tail(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LANECTL_STATE", str(tmp_path))
    log = EventLog()
    log.append("item.parked", {"reason": "a"}, item_id="it-1")
    log.append("item.requeued", {"reason": "b"}, item_id="it-1")
    log.append("item.parked", {"reason": "c"}, item_id="it-2")
    log.append("item.requeued", {"reason": "d"}, item_id="it-1")

    assert cli.main(["events", "--item", "it-1", "--type", "item.requeued", "-n", "1"]) == 0
    assert _types(capsys.readouterr().out) == ["item.requeued"]

    assert cli.main(["events", "--item", "it-1", "--type", "item.parked"]) == 0
    assert _types(capsys.readouterr().out) == ["item.parked"]
