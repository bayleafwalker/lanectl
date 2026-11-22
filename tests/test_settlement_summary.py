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


def receipt_args(tmp_path, ids):
    checkpoint = {"offset": 10, "digest": "a" * 64}
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"work_ids": ids, "checkpoint": checkpoint}))
    return request, checkpoint, tmp_path / "receipts"


def test_receipt_replays_exact_bytes_without_owner_or_inference(tmp_path, monkeypatch, capsys):
    import hashlib

    request, checkpoint, receipts = receipt_args(tmp_path, [4, 8])
    owner = Owner()
    calls = []
    monkeypatch.setattr(summary, "VuoroClient", lambda *args, **kwargs: owner)
    monkeypatch.setattr(summary, "summarize", lambda facts: calls.append(facts) or "Settled.")
    args = ["--request", str(request), "--receipt-dir", str(receipts), "--vuoro-token-file", "/unused"]
    assert summary.main(args) == 0
    first = capsys.readouterr()
    digest = hashlib.sha256(
        json.dumps({"checkpoint": checkpoint, "work_ids": [4, 8]},
                   sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert json.loads(first.out) == {
        "checkpoint": checkpoint, "work_ids": [4, 8], "request_digest": digest, "summary": "Settled.",
    }
    assert (receipts / f"{digest}.json").read_bytes() == first.out.encode()
    # Serialization does not change the identity of the same exact request.
    request.write_text(json.dumps({"checkpoint": checkpoint, "work_ids": [4, 8]}, indent=2))
    assert summary.main(args[:-2]) == 0
    assert capsys.readouterr() == first
    assert len(owner.calls) == 2 and len(calls) == 1


def test_empty_request_writes_an_acknowledgeable_receipt_without_clients(tmp_path, monkeypatch, capsys):
    request, checkpoint, receipts = receipt_args(tmp_path, [])
    monkeypatch.setattr(summary, "VuoroClient", lambda *a, **kw: pytest.fail("owner client created"))
    monkeypatch.setattr(summary, "summarize", lambda *a: pytest.fail("model called"))
    args = ["--request", str(request), "--receipt-dir", str(receipts)]
    assert summary.main(args) == 0
    first = capsys.readouterr().out
    result = json.loads(first)
    assert result["work_ids"] == []
    assert result["checkpoint"] == checkpoint
    assert result["summary"] is None
    assert (receipts / f"{result['request_digest']}.json").read_text() == first
    assert summary.main(args) == 0
    assert capsys.readouterr().out == first


def test_uncertain_inference_retains_marker_and_refuses_replay(tmp_path, monkeypatch, capsys):
    request, checkpoint, receipts = receipt_args(tmp_path, [4])
    owner = Owner()
    model_calls = []

    def offline(facts):
        model_calls.append(facts)
        raise OSError("private gateway response, token, or model text")

    monkeypatch.setattr(summary, "VuoroClient", lambda *args, **kwargs: owner)
    monkeypatch.setattr(summary, "summarize", offline)
    args = ["--request", str(request), "--receipt-dir", str(receipts), "--vuoro-token-file", "/unused"]
    assert summary.main(args) == 1
    first = capsys.readouterr()
    assert not first.out
    pending, = receipts.glob("*.pending")
    assert pending.name in first.err
    assert "private" not in first.err
    assert not list(receipts.glob("*.json"))
    assert summary.main(args) == 1
    assert capsys.readouterr() == first
    assert len(owner.calls) == len(model_calls) == 1


def test_concurrent_receipt_requests_only_infer_once(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    request, _, receipts = receipt_args(tmp_path, [4])
    owner = Owner()
    entered, waiting, release = Event(), Event(), Event()
    flock = summary.fcntl.flock

    def observe_lock(fd, flags):
        if entered.is_set():
            waiting.set()
        return flock(fd, flags)

    def model(facts):
        assert not entered.is_set()
        entered.set()
        assert release.wait(3)
        return "Settled."

    monkeypatch.setattr(summary, "VuoroClient", lambda *args, **kwargs: owner)
    monkeypatch.setattr(summary, "summarize", model)
    monkeypatch.setattr(summary.fcntl, "flock", observe_lock)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(summary.settlement_receipt, request, receipts, "/unused")
        try:
            assert entered.wait(2)
            second = pool.submit(summary.settlement_receipt, request, receipts, "/unused")
            assert waiting.wait(2)
        finally:
            release.set()
        assert first.result(3) == second.result(3)
    assert len(owner.calls) == 1


@pytest.mark.parametrize("value", [
    '{"work_ids":[4],"checkpoint":{"offset":0,"digest":null}}',
    '{"work_ids":[true],"checkpoint":{"offset":10,"digest":null}}',
    '{"work_ids":[],"checkpoint":{"offset":true,"digest":null}}',
    '{"work_ids":[],"work_ids":[4],"checkpoint":{"offset":0,"digest":null}}',
    '{"work_ids":[],"checkpoint":{"offset":0,"digest":null,"extra":1}}',
])
def test_invalid_request_creates_no_receipt(tmp_path, capsys, value):
    request, _, receipts = receipt_args(tmp_path, [])
    request.write_text(value)
    assert summary.main(["--request", str(request), "--receipt-dir", str(receipts)]) == 1
    assert not receipts.exists()
    assert capsys.readouterr().out == ""


def test_owner_read_failure_can_retry_before_model_fence(tmp_path, monkeypatch, capsys):
    request, _, receipts = receipt_args(tmp_path, [4])
    owner = Owner()
    original = owner.invoke
    failures = iter([True, False])
    model_calls = []

    def invoke(arguments):
        if next(failures):
            raise CoordinationError("owner read failed")
        return original(arguments)

    monkeypatch.setattr(owner, "invoke", invoke)
    monkeypatch.setattr(summary, "VuoroClient", lambda *a, **kw: owner)
    monkeypatch.setattr(summary, "summarize", lambda facts: model_calls.append(facts) or "Settled.")
    args = ["--request", str(request), "--receipt-dir", str(receipts), "--vuoro-token-file", "/unused"]
    assert summary.main(args) == 1
    assert capsys.readouterr().out == ""
    assert not list(receipts.glob("*.pending"))
    assert summary.main(args) == 0
    assert json.loads(capsys.readouterr().out)["summary"] == "Settled."
    assert len(model_calls) == 1


def test_receipt_publish_failure_has_no_stdout_and_blocks_duplicate_inference(tmp_path, monkeypatch, capsys):
    request, _, receipts = receipt_args(tmp_path, [4])
    owner = Owner()
    model_calls = []
    replace = summary.os.replace

    def obstruct_receipt(source, dest, **kw):
        if dest.endswith(".json"):
            raise OSError("fake private storage error")
        return replace(source, dest, **kw)

    monkeypatch.setattr(summary, "VuoroClient", lambda *a, **kw: owner)
    monkeypatch.setattr(summary, "summarize", lambda facts: model_calls.append(facts) or "Settled.")
    monkeypatch.setattr(summary.os, "replace", obstruct_receipt)
    args = ["--request", str(request), "--receipt-dir", str(receipts), "--vuoro-token-file", "/unused"]
    assert summary.main(args) == 1
    first = capsys.readouterr()
    assert not first.out and "fake private" not in first.err
    assert not list(receipts.glob("*.json"))
    assert not list(receipts.glob("*.tmp"))
    monkeypatch.setattr(summary.os, "replace", replace)
    assert summary.main(args) == 1
    assert capsys.readouterr() == first
    assert len(owner.calls) == len(model_calls) == 1


def test_positional_cli_still_returns_plain_text(monkeypatch, capsys):
    monkeypatch.setattr(summary, "VuoroClient", lambda *a, **kw: Owner())
    monkeypatch.setattr(summary, "summarize", lambda facts: "Plain summary")
    assert summary.main(["--vuoro-token-file", "/unused", "4"]) == 0
    assert capsys.readouterr().out == "Plain summary\n"


def test_trusted_scheduler_facts_are_bound_to_the_exact_request(tmp_path, monkeypatch, capsys):
    request, _, receipts = receipt_args(tmp_path, [4])
    owner = Owner()
    owner.expected_environment = "vuoro-cloud-ws-test"
    facts = summary.owner_facts(owner, json.loads(request.read_text()))
    path = tmp_path / "owner-facts.json"
    path.write_text(json.dumps({**facts, "request_digest": "0" * 64}))
    monkeypatch.setattr(summary, "VuoroClient", lambda *a, **kw: pytest.fail("worker fetched the owner"))
    calls = []
    monkeypatch.setattr(summary, "summarize", lambda facts: calls.append(facts) or "Accepted.")
    args = ["--request", str(request), "--receipt-dir", str(receipts), "--facts-file", str(path)]
    assert summary.main(args) == 1
    assert not calls and not list(receipts.glob("*.pending"))
    capsys.readouterr()

    path.write_text(json.dumps(facts))
    assert summary.main(args) == 0
    result = capsys.readouterr().out
    assert json.loads(result)["summary"] == "Accepted."
    assert calls == [facts["facts"]]
    path.unlink()
    assert summary.main(args) == 0
    assert capsys.readouterr().out == result and len(calls) == 1
