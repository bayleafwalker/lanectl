import json

import pytest

from lanectl import settlement_summary as summary
from lanectl.coordination import CoordinationError


class Owner:
    def __init__(self):
        self.calls = []

    def envelope(self, operation, arguments, key):
        self.calls.append((operation, arguments, key))
        return arguments

    def invoke(self, arguments):
        return {"authority": "sprintctl", "state": "ok", "item": {
            "work_id": arguments["work_id"], "status": "done",
            "title": "A settlement", "resolution": "accepted", "private_notes": "omit",
        }}


def test_batch_selects_only_public_settlement_facts():
    owner = Owner()
    facts = summary.settlements(owner, [4, 8])
    assert owner.calls == [
        ("work.public.item-v1", {"work_id": 4}, None),
        ("work.public.item-v1", {"work_id": 8}, None),
    ]
    assert facts == [
        {"work_id": work_id, "title": "A settlement", "resolution": "accepted"}
        for work_id in (4, 8)
    ]


@pytest.mark.parametrize("ids", [[], [0], [1, 1], list(range(1, 34))])
def test_rejects_invalid_batches(ids):
    with pytest.raises(CoordinationError):
        summary.settlements(Owner(), ids)


def test_nonterminal_item_cannot_reach_model(monkeypatch):
    original = Owner.invoke

    def running(self, arguments):
        response = original(self, arguments)
        response["item"]["status"] = "active"
        return response

    monkeypatch.setattr(Owner, "invoke", running)
    with pytest.raises(CoordinationError, match="terminal settlement"):
        summary.settlements(Owner(), [4])


def test_sends_one_bounded_request_to_loopback_gateway(monkeypatch):
    class Gateway:
        status = 200

        def __init__(self, host, port, *, timeout):
            assert (host, port) == ("127.0.0.1", 18021)

        def request(self, method, path, body, headers):
            assert (method, path) == ("POST", "/v1/messages")
            assert "Authorization" not in headers
            request = json.loads(body)
            assert request["max_tokens"] == 1536
            assert json.loads(request["messages"][0]["content"]) == [{"work_id": 4}]

        def getresponse(self):
            return self

        def read(self, size):
            return b'{"stop_reason":"end_turn","content":[{"type":"text","text":"Item 4 settled."}]}'

        def close(self):
            pass

    monkeypatch.setattr(summary.http.client, "HTTPConnection", Gateway)
    assert summary.summarize([{"work_id": 4}]) == "Item 4 settled."
