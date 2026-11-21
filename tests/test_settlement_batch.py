import json

import pytest

from lanectl.contracts import make_event
from lanectl.settlement_batch import main, next_batch


def settled(work_id, **overrides):
    return make_event("work.synced", dict(
        work=f"lanectl#{work_id}", train_id="train-1", closed=True,
        ok=True, owner_reported=True,
    ) | overrides)


def test_selects_only_unique_owner_confirmed_lanectl_settlements():
    events = [
        settled(1, owner_reported=False),
        settled(2, closed=False),
        settled(3, work="other#3"),
        settled(4),
        settled(4),
        settled(5),
    ]
    selected = next_batch(events)
    assert selected["work_ids"] == [4, 5]
    assert next_batch(events + [settled(4), settled(6)], **selected["checkpoint"])["work_ids"] == [6]


def test_batch_does_not_advance_past_unselected_items():
    events = [settled(i) for i in range(1, 35)]
    first = next_batch(events)
    assert first["work_ids"] == list(range(1, 33))
    assert next_batch(events, **first["checkpoint"])["work_ids"] == [33, 34]


def test_checkpoint_refuses_changed_ledger():
    checkpoint = next_batch([settled(4)])["checkpoint"]
    with pytest.raises(ValueError, match="checkpoint"):
        next_batch([settled(5)], **checkpoint)


def test_read_only_cli_does_not_create_ledger(tmp_path, capsys):
    ledger = tmp_path / "events.jsonl"
    assert main([str(ledger)]) == 1
    assert not ledger.exists()
    ledger.write_text(json.dumps(settled(1)) + "\n")
    assert main([str(ledger)]) == 0
    assert json.loads(capsys.readouterr().out)["work_ids"] == [1]
