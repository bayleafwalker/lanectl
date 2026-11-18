"""Transport regressions from an independent review of the resident gateway."""
from __future__ import annotations

from dataclasses import replace
from email.message import Message
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import sqlite3
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from lanectl import resident_gateway as gateway


def payload(**changes):
    return json.dumps({"model": "worker-fast", "messages": [{"role": "user", "content": "draft"}],
                       "stream": True, **changes}).encode()


class Response(io.BytesIO):
    status = 200

    def __init__(self, content, *, kind="text/event-stream"):
        super().__init__(content)
        self.headers = Message()
        self.headers["Content-Type"] = kind


class BrokenResponse(Response):
    def __init__(self):
        super().__init__(b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n')
        self.calls = 0

    def read1(self, size=-1):
        self.calls += 1
        if self.calls > 1:
            raise OSError("simulated upstream connection loss")
        return super().read1(size)


class Opener:
    def __init__(self, response):
        self.response = response

    def open(self, request, timeout):
        return self.response


@pytest.fixture
def running(tmp_path):
    opened = []

    def start(response=None, *, opener=None, **changes):
        config = gateway.validate_config({
            "schema": "lanectl.resident-gateway/v1", "route": "local/worker-fast",
            "upstream_base_url": "https://peer.example.invalid:8021/v1", "listen_port": 18021,
            "session_id": "resident-review", "state_file": str(tmp_path / "requests.sqlite3"),
            **changes,
        })
        app = gateway.Gateway(replace(config, listen_port=0), "never-disclose-me",
                              opener=opener or Opener(response))
        server = app.make_server()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        opened.append((server, thread))
        return app, f"http://127.0.0.1:{server.server_port}/v1/chat/completions"

    yield start
    for server, thread in opened:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def read(url, data=None):
    req = urllib.request.Request(url, data=payload() if data is None else data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3) as response:
        return response.status, response.read()


TRANSPORT_FAILURES = (urllib.error.HTTPError, http.client.IncompleteRead,
                      http.client.RemoteDisconnected, ConnectionResetError)


def test_oversize_upstream_response_is_not_a_successful_empty_http_200(running):
    app, url = running(Response(b"x" * 2048), max_response_bytes=1024)
    with pytest.raises(TRANSPORT_FAILURES):
        read(url)
    assert app.inflight.acquire(blocking=False)
    app.inflight.release()


def test_upstream_read_failure_does_not_become_a_clean_successful_eof(running):
    app, url = running(BrokenResponse())
    with pytest.raises(TRANSPORT_FAILURES):
        read(url)
    with sqlite3.connect(app.config.state_file) as db:
        outcomes = [row[0] for row in db.execute("SELECT outcome FROM requests")]
    assert outcomes != ["completed"]


@pytest.mark.parametrize("content", [
    b'data: {"choices":[{"delta":{"content":"unfinished"}}]}\n\n',
    b'data: {"choices":[{"delta":{"content":"data: [DONE]"}}]}\n\n',
])
def test_sse_requires_a_real_done_event_not_just_upstream_eof(running, content):
    app, url = running(Response(content))
    with pytest.raises(TRANSPORT_FAILURES):
        read(url)
    with sqlite3.connect(app.config.state_file) as db:
        assert db.execute("SELECT count(*) FROM requests WHERE outcome='completed'").fetchone()[0] == 0


def test_completed_sse_preserves_done_marker_split_between_network_reads(running):
    class SplitResponse(Response):
        def read1(self, size=-1):
            return super().read1(min(size, 3))
    content = b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'
    _, url = running(SplitResponse(content))
    assert read(url) == (200, content)


def test_request_deadline_does_not_restart_for_each_upstream_read(running, monkeypatch, tmp_path):
    # Real HTTPResponse/socket, so the test checks blocking reads rather than a
    # mocked monotonic clock. TLS and destination policy are tested elsewhere.
    content = b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'

    first_fragment_sent = threading.Event()

    class SlowPeer(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            try:
                time.sleep(.7)
                self.wfile.write(content[:12])
                self.wfile.flush()
                first_fragment_sent.set()
                time.sleep(.7)
                self.wfile.write(content[12:])
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

    peer = ThreadingHTTPServer(("127.0.0.1", 0), SlowPeer)
    peer.daemon_threads = True
    thread = threading.Thread(target=peer.serve_forever, daemon=True)
    thread.start()

    class PeerConnection(http.client.HTTPConnection):
        def __init__(self, host, port=None, *, timeout, context):
            super().__init__("127.0.0.1", peer.server_port, timeout=timeout)

    monkeypatch.setattr(gateway.http.client, "HTTPSConnection", PeerConnection)
    config = gateway.validate_config({
        "schema": "lanectl.resident-gateway/v1", "route": "local/worker-fast",
        "upstream_base_url": "https://peer.example.invalid:8021/v1", "listen_port": 18021,
        "session_id": "resident-review", "state_file": str(tmp_path / "requests.sqlite3"),
        "timeout_s": 1,
    })

    try:
        _, url = running(opener=gateway.build_opener(config), timeout_s=1)
        with pytest.raises(TRANSPORT_FAILURES):
            read(url)
        # A rolling one-second timeout would accept both fragments. Demand
        # the transport failure after the first successful upstream write.
        assert first_fragment_sent.is_set()
    finally:
        peer.shutdown()
        peer.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("status", [200, 302])
def test_production_transport_handles_content_length_eof_and_never_follows_redirect(
        running, monkeypatch, tmp_path, status):
    content = b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'
    calls = []

    class Peer(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            calls.append(self.path)
            self.send_response(status)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(content)))
            if status == 302:
                self.send_header("Location", "https://attacker.example.invalid/exfiltrate")
            self.end_headers()
            self.wfile.write(content)

    peer = ThreadingHTTPServer(("127.0.0.1", 0), Peer)
    peer.daemon_threads = True
    thread = threading.Thread(target=peer.serve_forever, daemon=True)
    thread.start()

    class PeerConnection(http.client.HTTPConnection):
        def __init__(self, host, port=None, *, timeout, context):
            super().__init__("127.0.0.1", peer.server_port, timeout=timeout)

    monkeypatch.setattr(gateway.http.client, "HTTPSConnection", PeerConnection)
    config = gateway.validate_config({
        "schema": "lanectl.resident-gateway/v1", "route": "local/worker-fast",
        "upstream_base_url": "https://peer.example.invalid:8021/v1", "listen_port": 18021,
        "session_id": "resident-review", "state_file": str(tmp_path / "requests.sqlite3"),
    })
    try:
        _, url = running(opener=gateway.build_opener(config))
        if status == 200:
            assert read(url) == (200, content)
        else:
            with pytest.raises(urllib.error.HTTPError) as exc:
                read(url)
            assert exc.value.code == 502
            assert "Location" not in exc.value.headers
        assert calls == ["/v1/chat/completions"]
    finally:
        peer.shutdown()
        peer.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("data", [
    b'{"model":"worker-fast","messages":[{"role":"user","content":"\\ud800"}]}',
    b'{"model":"worker-fast","messages":[{"role":"user","content":"x"}],"temperature":1e9999}',
])
def test_unserializable_json_is_a_bounded_client_error(tmp_path, data):
    config = gateway.validate_config({
        "schema": "lanectl.resident-gateway/v1", "route": "local/worker-fast",
        "upstream_base_url": "https://peer.example.invalid:8021/v1",
        "session_id": "resident-review", "state_file": str(tmp_path / "requests.sqlite3"),
    })
    with pytest.raises(gateway.GatewayError):
        gateway.normalize_request(config, data)


def test_oversized_numeric_content_length_gets_client_error_without_upstream(running):
    _, url = running(Response(b"data: [DONE]\n\n"))
    parsed = urllib.parse.urlsplit(url)
    with socket.create_connection((parsed.hostname, parsed.port), timeout=3) as client:
        client.sendall(("POST /v1/chat/completions HTTP/1.1\r\nHost: localhost\r\n"
                        "Content-Type: application/json\r\nContent-Length: " + "9" * 5000 +
                        "\r\nConnection: close\r\n\r\n").encode())
        status = client.recv(4096).split(b"\r\n", 1)[0]
    assert status.startswith(b"HTTP/1.1 400")


def test_ledger_closes_connections_without_waiting_for_python_gc(tmp_path, monkeypatch):
    original_connect = sqlite3.connect
    opened, closed = [], set()

    class TrackedConnection(sqlite3.Connection):
        def close(self):
            super().close()
            closed.add(id(self))

    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs, factory=TrackedConnection)
        opened.append(connection)
        return connection

    monkeypatch.setattr(gateway.sqlite3, "connect", connect)
    try:
        ledger = gateway.RequestLedger(tmp_path / "requests.sqlite3")
        identifier = ledger.reserve("local/worker-fast", None, 3600)
        ledger.finish(identifier, "completed", 200)
        all_closed_at_return = len(closed) == len(opened) == 3
    finally:
        for connection in opened:
            connection.close()
    assert all_closed_at_return
