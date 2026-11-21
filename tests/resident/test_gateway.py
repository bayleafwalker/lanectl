"""The credential gateway is a fixed model capability, not a general proxy."""
from dataclasses import replace
from email.message import Message
import io
import json
from pathlib import Path
import ssl
import socket
import http.client
import errno
import threading
from types import SimpleNamespace
import urllib.error
import urllib.request

import pytest

from lanectl import resident_gateway as gateway


def raw_config(tmp_path, route="local/worker-fast"):
    value = {
        "schema": "lanectl.resident-gateway/v1", "route": route,
        "upstream_base_url": "https://model-peer.example.invalid:8021/v1",
        "listen_port": 18021, "credential_name": "upstream-token",
        "session_id": "resident-writer-one", "state_file": str(tmp_path / "requests.sqlite3"),
        "max_output_tokens": 8192, "timeout_s": 900,
    }
    if route.startswith("opencode-go/"):
        value.update(upstream_base_url="https://opencode.ai/inference/go/openai/v1",
                     max_requests_per_window=120, window_s=3600)
    return value


def payload(model="worker-fast", **kwargs):
    return json.dumps({"model": model, "messages": [{"role": "user", "content": "Draft a scene"}],
                       **kwargs}).encode()


def test_routes_and_go_allowance_are_explicit(tmp_path):
    local = gateway.validate_config(raw_config(tmp_path))
    assert local.model == "worker-fast"
    assert local.max_requests_per_window is None
    go = gateway.validate_config(raw_config(tmp_path, "opencode-go/deepseek-v4.1-flash"))
    assert go.model == "deepseek-v4.1-flash"
    for change in ({"route": "auto"}, {"fallback": "opencode-go"},
                   {"listen_port": 80}, {"timeout_s": True},
                   {"upstream_base_url": "http://127.0.0.1:8020/v1"},
                   {"upstream_base_url": "https://user:secret@peer.invalid/v1"},
                   {"upstream_base_url": "https://peer.invalid/v1?target=other"}):
        with pytest.raises(gateway.GatewayError):
            gateway.validate_config(dict(raw_config(tmp_path), **change))
    go_raw = raw_config(tmp_path, "opencode-go/deepseek-v4.1-flash")
    for change in ({"max_requests_per_window": None}, {"max_requests_per_window": 0},
                   {"upstream_base_url": "https://opencode.ai/inference/openai/v1"},
                   {"upstream_base_url": "https://opencode.ai.evil.invalid/inference/go/openai/v1"}):
        with pytest.raises(gateway.GatewayError):
            gateway.validate_config(dict(go_raw, **change))


def test_model_output_cap_and_text_only_request(tmp_path):
    config = gateway.validate_config(raw_config(tmp_path))
    normalized = json.loads(gateway.normalize_request(config, payload()))
    assert normalized["max_tokens"] == 8192
    assert normalized["model"] == "worker-fast"
    assert json.loads(gateway.normalize_request(config, payload(max_completion_tokens=32)))["max_completion_tokens"] == 32
    for body in (payload("different"), payload(max_tokens=8193), payload(max_tokens=True),
                 payload(max_tokens=3, max_completion_tokens=4), payload(base_url="https://elsewhere.invalid"),
                 payload(n=2), payload(messages=[]), payload(store=True),
                 payload(messages=[{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://elsewhere.invalid"}}]}]),
                 b'{"model":"worker-fast","model":"other","messages":[]}',
                 b'{"model":"worker-fast","messages":[],"temperature":NaN}'):
        with pytest.raises(gateway.GatewayError):
            gateway.normalize_request(config, body)


def test_normal_native_tool_round_trip_is_preserved(tmp_path):
    config = gateway.validate_config(raw_config(tmp_path))
    messages = [
        {"role": "user", "content": "Read the chapter"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "read", "arguments": '{"path":"drafts/chapter.md"}'}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "A chapter."},
    ]
    value = json.loads(gateway.normalize_request(config, payload(messages=messages, stream=True,
        tools=[{"type": "function", "function": {"name": "read", "parameters": {"type": "object"}}}])))
    assert value["messages"] == messages
    assert value["stream"] is True


def test_rolling_go_counter_survives_restart_and_counts_failed_calls(tmp_path):
    path = tmp_path / "requests.sqlite3"
    ledger = gateway.RequestLedger(path)
    first = ledger.reserve("go", 2, 3600, now=10000)
    ledger.finish(first, "upstream-error", 503)
    second = gateway.RequestLedger(path).reserve("go", 2, 3600, now=10001)
    assert second != first
    with pytest.raises(gateway.RateLimited):
        gateway.RequestLedger(path).reserve("go", 2, 3600, now=10002)
    # Clock rollback cannot hide already reserved requests in the future.
    with pytest.raises(gateway.RateLimited):
        ledger.reserve("go", 2, 3600, now=9999)
    assert ledger.reserve("go", 2, 3600, now=13602)


def test_local_usage_has_no_aggregate_counter_limit(tmp_path):
    ledger = gateway.RequestLedger(tmp_path / "requests.sqlite3")
    for _ in range(5):
        assert ledger.reserve("local/worker-fast", None, 3600, now=1)


def test_ledger_refuses_symlink_and_unknown_schema(tmp_path):
    target = tmp_path / "target"
    target.write_text("not sqlite")
    link = tmp_path / "requests.sqlite3"
    link.symlink_to(target)
    with pytest.raises(gateway.GatewayError):
        gateway.RequestLedger(link)


class Response(io.BytesIO):
    status = 200

    def __init__(self, body=b'{"choices":[{"message":{"content":"ok"}}]}', content_type="application/json"):
        super().__init__(body)
        self.headers = Message()
        self.headers["Content-Type"] = content_type


class Upstream:
    def __init__(self, response=None, failure=None):
        self.requests = []
        self.response = response
        self.failure = failure

    def open(self, request, timeout):
        self.requests.append(request)
        if self.failure:
            raise self.failure
        return self.response or Response()


@pytest.fixture
def running(tmp_path):
    servers = []

    def start(*, route="local/worker-fast", upstream=None, federation=None, **settings):
        config = gateway.validate_config(dict(raw_config(tmp_path, route), **settings))
        # Ephemeral test listener; production configuration rejects port zero.
        app = gateway.Gateway(replace(config, listen_port=0), "protected-upstream-secret",
                              opener=upstream or Upstream(), federation=federation)
        server = app.make_server()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread))
        return app, f"http://127.0.0.1:{server.server_port}"

    yield start
    for server, thread in servers:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request(origin, path="/v1/chat/completions", body=None, headers=None, method=None):
    req = urllib.request.Request(origin + path, data=payload() if body is None and method != "GET" else body,
        headers={"Content-Type": "application/json", **(headers or {})}, method=method)
    with urllib.request.urlopen(req, timeout=3) as response:
        return response.status, response.headers, response.read()


def test_appservice_readiness_requires_the_live_pilot_route(running, monkeypatch):
    from lanectl import adapters_opencode, sandbox

    upstream = Upstream()
    _, origin = running(upstream=upstream)
    monkeypatch.setattr(adapters_opencode, "APPSERVICE_GATEWAY_PORT", int(origin.rsplit(":", 1)[1]))
    with pytest.raises(RuntimeError, match="does not advertise the fixed pilot route"):
        sandbox.probe_appservice_gateway()

    _, origin = running(route=gateway.GO_ROUTE, upstream=upstream)
    monkeypatch.setattr(adapters_opencode, "APPSERVICE_GATEWAY_PORT", int(origin.rsplit(":", 1)[1]))
    sandbox.probe_appservice_gateway()
    assert upstream.requests == []


def test_gateway_keeps_credentials_session_and_destination_out_of_client_control(running):
    upstream = Upstream()
    app, origin = running(route="opencode-go/deepseek-v4.1-flash", upstream=upstream)
    status, _, body = request(origin, body=payload("deepseek-v4.1-flash"), headers={
        "Authorization": "Bearer attacker", "X-OpenCode-Session": "attacker-session",
        "User-Agent": "attacker", "X-Upstream": "https://evil.invalid"})
    assert status == 200 and b'"ok"' in body
    forwarded = upstream.requests[0]
    assert forwarded.full_url == "https://opencode.ai/inference/go/openai/v1/chat/completions"
    headers = {key.lower(): value for key, value in forwarded.header_items()}
    assert headers["authorization"] == "Bearer protected-upstream-secret"
    assert headers["x-opencode-session"] == "resident-writer-one"
    assert headers["user-agent"].startswith("lanectl-resident/")
    assert "x-upstream" not in headers
    assert b"protected-upstream-secret" not in body


def test_catalog_and_health_are_explicitly_not_generation_readiness(running):
    app, origin = running()
    _, _, health = request(origin, "/healthz", method="GET")
    assert json.loads(health)["inference_readiness"] == "not-probed"
    _, _, models = request(origin, "/v1/models", method="GET")
    assert [entry["id"] for entry in json.loads(models)["data"]] == ["worker-fast"]
    assert app.opener.requests == []


def test_path_and_model_refusal_never_contacts_upstream(running):
    app, origin = running()
    for path, data in (("/v1/embeddings", payload()), ("/v1/chat/completions?other=1", payload()),
                       ("/v1/chat/completions", payload("other")), ("/v1/models", payload())):
        with pytest.raises(urllib.error.HTTPError) as exc:
            request(origin, path, body=data)
        assert exc.value.code in (400, 404, 405)
    assert app.opener.requests == []


def test_concurrency_one_and_persistent_rate_limit(running):
    app, origin = running(route="opencode-go/deepseek-v4.1-flash", max_requests_per_window=1)
    app.inflight.acquire()
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            request(origin, body=payload("deepseek-v4.1-flash"))
        assert exc.value.code == 429
    finally:
        app.inflight.release()
    request(origin, body=payload("deepseek-v4.1-flash"))
    with pytest.raises(urllib.error.HTTPError) as exc:
        request(origin, body=payload("deepseek-v4.1-flash"))
    assert exc.value.code == 429
    assert len(app.opener.requests) == 1


def test_errors_cannot_leak_upstream_bodies_or_redirects(running):
    error = urllib.error.HTTPError("https://selected.invalid", 302, "moved",
        {"Location": "https://evil.invalid"}, io.BytesIO(b"protected-upstream-secret"))
    app, origin = running(upstream=Upstream(failure=error))
    with pytest.raises(urllib.error.HTTPError) as exc:
        request(origin)
    assert exc.value.code == 502
    assert exc.value.headers.get("Location") is None
    assert b"protected-upstream-secret" not in exc.value.read()
    assert len(app.opener.requests) == 1


def test_sse_bytes_are_forwarded_without_changing_tool_calls(running):
    sse = b'data: {"choices":[{"delta":{"tool_calls":[]}}]}\n\ndata: [DONE]\n\n'
    app, origin = running(upstream=Upstream(response=Response(sse, "text/event-stream")))
    status, headers, body = request(origin, body=payload(stream=True))
    assert status == 200 and headers["Content-Type"] == "text/event-stream"
    assert body == sse


def test_anthropic_messages_are_pinned_and_streamed(running):
    sse = (
        b'event: content_block_start\ndata: {"type":"content_block_start",'
        b'"content_block":{"type":"tool_use","id":"toolu_1","name":"read","input":{}}}\n\n'
        b'event: message_stop\ndata: {"type":"message_stop"}\n\n'
    )
    upstream = Upstream(response=Response(sse, "text/event-stream"))
    app, origin = running(route=gateway.ANTHROPIC_ROUTE, upstream=upstream,
                        upstream_base_url=gateway.ANTHROPIC_BASE, max_requests_per_window=3)
    model = gateway.ANTHROPIC_ROUTE.split("/")[1]
    for path, body, status in (
        ("/v1/chat/completions", payload(model, max_tokens=32), 404),
        ("/v1/messages", payload("another-model", max_tokens=32), 400),
        ("/v1/messages", payload(model, max_tokens=8193), 400),
        ("/v1/messages", payload(model, max_tokens=32, thinking={"type": "enabled"}), 400),
        ("/v1/messages", payload(model, max_tokens=32, tools=[{"type": "web_search"}]), 400),
    ):
        with pytest.raises(urllib.error.HTTPError) as error:
            request(origin, path=path, body=body)
        assert error.value.code == status
    assert upstream.requests == []
    cache_control = {"type": "ephemeral"}
    body = payload(model, max_tokens=32, stream=True,
                   thinking={"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}},
                   system=[{"type": "text", "text": "system", "cache_control": cache_control}],
                   tools=[{"name": "read", "input_schema": {"type": "object"}, "cache_control": cache_control}])
    status, _, response = request(origin, path="/v1/messages", body=body,
                                  headers={"x-api-key": "untrusted", "anthropic-version": "untrusted"})
    assert status == 200 and response == sse
    forwarded = upstream.requests[0]
    assert forwarded.full_url == gateway.ANTHROPIC_BASE + "/messages"
    normalized = json.loads(forwarded.data)
    assert "thinking" not in normalized
    assert normalized["system"][0]["cache_control"] == cache_control
    assert normalized["tools"][0]["cache_control"] == cache_control
    assert gateway.build_opener(app.config).url == forwarded.full_url
    headers = {k.lower(): v for k, v in forwarded.header_items()}
    assert headers["x-api-key"] == "protected-upstream-secret"
    assert headers["anthropic-version"] == "2023-06-01"
    assert "authorization" not in headers


def test_claude_federation_sends_only_bearer_and_rereads_rotated_projection(tmp_path, running):
    raw = dict(raw_config(tmp_path, gateway.ANTHROPIC_ROUTE), upstream_base_url=gateway.ANTHROPIC_BASE,
               max_requests_per_window=3)
    config = gateway.validate_config(raw)
    token_file = tmp_path / "token"
    token_file.write_text("header.claims.signature")
    env = {
        "ANTHROPIC_IDENTITY_TOKEN_FILE": str(token_file),
        "ANTHROPIC_FEDERATION_RULE_ID": "fdrl_example",
        "ANTHROPIC_ORGANIZATION_ID": "00000000-0000-0000-0000-000000000000",
        "ANTHROPIC_WORKSPACE_ID": "wrkspc_example",
        "ANTHROPIC_SERVICE_ACCOUNT_ID": "svac_example",
    }
    response = b'{"access_token":"sk-ant-oat01-test","token_type":"Bearer","expires_in":600,"scope":"workspace:inference"}'
    exchange = Upstream(response=Response(response))
    auth = gateway.AnthropicFederation(config, env, opener=exchange)
    upstream = Upstream(response=Response(b'{"content":[]}'))
    app, origin = running(route=config.route, upstream=upstream, federation=auth,
                        upstream_base_url=config.upstream_base_url, max_requests_per_window=3)
    assert request(origin, path="/v1/messages", body=payload(config.model, max_tokens=32))[0] == 200
    with app.inflight:
        assert auth.bearer() == "sk-ant-oat01-test"
    assert len(exchange.requests) == 1
    exchange_request = exchange.requests[0]
    assert exchange_request.full_url == gateway.ANTHROPIC_EXCHANGE
    assert json.loads(exchange_request.data) == {
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": "header.claims.signature",
        "federation_rule_id": "fdrl_example",
        "organization_id": "00000000-0000-0000-0000-000000000000",
        "workspace_id": "wrkspc_example",
        "service_account_id": "svac_example",
    }
    headers = {key.lower(): value for key, value in upstream.requests[0].header_items()}
    assert headers["authorization"] == "Bearer sk-ant-oat01-test" and "x-api-key" not in headers

    token_file.write_text("header.rotated.signature")
    auth.refresh_at = 0
    exchange.response = Response(response.replace(b"test", b"next"))
    assert auth.bearer() == "sk-ant-oat01-next"
    assert json.loads(exchange.requests[1].data)["assertion"] == "header.rotated.signature"

    auth.refresh_at = 0
    exchange.response = Response(b'{"access_token":"invalid"}')
    with pytest.raises(urllib.error.HTTPError) as error:
        request(origin, path="/v1/messages", body=payload(config.model, max_tokens=32))
    assert error.value.code == 502 and len(upstream.requests) == 1

    with pytest.raises(gateway.GatewayError):
        gateway.AnthropicFederation(config, dict(env, ANTHROPIC_API_KEY=""))


def test_anthropic_requires_exact_origin_and_explicit_allowance(tmp_path):
    raw = raw_config(tmp_path, gateway.ANTHROPIC_ROUTE)
    with pytest.raises(gateway.GatewayError, match="Messages API origin"):
        gateway.validate_config(dict(raw, max_requests_per_window=3))
    with pytest.raises(gateway.GatewayError, match="request allowance"):
        gateway.validate_config(dict(raw, upstream_base_url=gateway.ANTHROPIC_BASE))


def test_appservice_paid_profile_requires_matching_config_and_listener(running, monkeypatch):
    from lanectl import adapters_opencode, runner, sandbox

    monkeypatch.delenv("LANECTL_APPSERVICE_ROUTE", raising=False)
    assert adapters_opencode.appservice_route() == gateway.GO_ROUTE
    monkeypatch.setenv("LANECTL_APPSERVICE_ROUTE", gateway.ANTHROPIC_ROUTE)
    config = adapters_opencode.appservice_provider_config()
    provider, model = config["model"].split("/")
    assert gateway.ANTHROPIC_ROUTE.endswith("/" + model)
    assert config["providers"][provider]["package"] == "@opencode/ai/providers/anthropic"
    assert config["providers"][provider]["settings"]["apiKey"] == "resident-gateway"
    assert runner.provider_for(gateway.ANTHROPIC_ROUTE) == "anthropic-api"

    _, go_origin = running(route=gateway.GO_ROUTE)
    monkeypatch.setattr(adapters_opencode, "APPSERVICE_GATEWAY_PORT", int(go_origin.rsplit(":", 1)[1]))
    with pytest.raises(RuntimeError, match="does not advertise the fixed pilot route"):
        sandbox.probe_appservice_gateway()
    _, paid_origin = running(route=gateway.ANTHROPIC_ROUTE,
                             upstream_base_url=gateway.ANTHROPIC_BASE, max_requests_per_window=3)
    monkeypatch.setattr(adapters_opencode, "APPSERVICE_GATEWAY_PORT", int(paid_origin.rsplit(":", 1)[1]))
    sandbox.probe_appservice_gateway()

    monkeypatch.setenv("LANECTL_APPSERVICE_ROUTE", "auto")
    with pytest.raises(ValueError, match="unknown appservice model route"):
        adapters_opencode.appservice_provider_config()


def test_secret_loader_uses_only_named_systemd_credential(tmp_path):
    path = tmp_path / "upstream-token"
    path.write_text("my-private-token\n")
    path.chmod(0o600)
    assert gateway.read_credential("upstream-token", {"CREDENTIALS_DIRECTORY": str(tmp_path)}) == "my-private-token"
    with pytest.raises(gateway.GatewayError):
        gateway.read_credential("upstream-token", {"API_KEY": "must-not-be-used"})
    for value in ("../upstream-token", "/tmp/key"):
        with pytest.raises(gateway.GatewayError):
            gateway.read_credential(value, {"CREDENTIALS_DIRECTORY": str(tmp_path)})
    path.chmod(0o644)
    with pytest.raises(gateway.GatewayError):
        gateway.read_credential("upstream-token", {"CREDENTIALS_DIRECTORY": str(tmp_path)})


def test_appservice_secret_loader_requires_read_only_mount_and_private_file(tmp_path, monkeypatch):
    path = tmp_path / "upstream-token"
    path.write_text("synthetic-pilot-token\n")
    path.chmod(0o400)
    with pytest.raises(gateway.GatewayError, match="private regular file"):
        gateway.read_credential(path.name, appservice_directory=tmp_path)

    monkeypatch.setattr(gateway.os, "fstatvfs", lambda fd: SimpleNamespace(f_flag=gateway.os.ST_RDONLY))
    assert gateway.read_credential(path.name, appservice_directory=tmp_path) == "synthetic-pilot-token"
    path.chmod(0o444)
    with pytest.raises(gateway.GatewayError, match="private regular file"):
        gateway.read_credential(path.name, appservice_directory=tmp_path)
    link = tmp_path / "linked-token"
    link.symlink_to(path)
    with pytest.raises(OSError) as exc:
        gateway.read_credential(link.name, appservice_directory=tmp_path)
    assert exc.value.errno == errno.ELOOP


def test_real_transport_refuses_redirect_and_ambient_proxy(tmp_path, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://attacker.invalid:8123")
    config = gateway.validate_config(raw_config(tmp_path))
    opener = gateway.build_opener(config)
    assert isinstance(opener, gateway.FixedHTTPS)
    assert opener.parsed.hostname == "model-peer.example.invalid"
    assert opener.context.check_hostname
    assert opener.context.verify_mode == ssl.CERT_REQUIRED
    with pytest.raises(gateway.GatewayError, match="different destination"):
        opener.open(urllib.request.Request("https://elsewhere.invalid/v1/chat/completions", data=b"{}"), timeout=1)


def unix_socket():
    try:
        return socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    except OSError as exc:
        if exc.errno in (errno.EPERM, errno.EAFNOSUPPORT):
            pytest.skip("executor denies AF_UNIX; actual Unix transport remains a target-host gate")
        raise


def test_systemd_unix_listener_serves_the_same_fixed_capability(tmp_path):
    path = tmp_path / "model.sock"
    config = gateway.validate_config(dict(raw_config(tmp_path), listen_socket=str(path)))
    listener = unix_socket()
    listener.bind(str(path))
    listener.listen(8)
    app = gateway.Gateway(config, "private-token", opener=Upstream())
    server = app.make_server(activated_socket=listener)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = http.client.HTTPConnection("localhost", timeout=2)
    client.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.sock.settimeout(2)
    client.sock.connect(str(path))
    try:
        client.request("POST", "/v1/chat/completions", body=payload(), headers={"Content-Type": "application/json"})
        response = client.getresponse()
        assert response.status == 200 and b'"ok"' in response.read()
        assert len(app.opener.requests) == 1
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_unix_activation_refuses_foreign_or_absent_listener(tmp_path):
    config = gateway.validate_config(dict(raw_config(tmp_path), listen_socket=str(tmp_path / "model.sock")))
    app = gateway.Gateway(config, "token", opener=Upstream())
    with pytest.raises(gateway.GatewayError, match="socket activation"):
        gateway.activation_socket(config, {})
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        with pytest.raises(gateway.GatewayError, match="Unix listener"):
            app.make_server(activated_socket=listener)
    with unix_socket() as listener:
        listener.bind(str(tmp_path / "other.sock"))
        listener.listen(1)
        with pytest.raises(gateway.GatewayError, match="Unix listener"):
            app.make_server(activated_socket=listener)


def test_unix_activation_requires_exact_socket_capability_without_os_fixture(tmp_path):
    config = gateway.validate_config(dict(raw_config(tmp_path), listen_socket=str(tmp_path / "model.sock")))

    class Listener:
        family, type = socket.AF_UNIX, socket.SOCK_STREAM

        def getsockname(self):
            return str(config.listen_socket)

        def getsockopt(self, level, option):
            return 1

    listener = Listener()
    gateway.validate_listener(config, listener)
    listener.getsockname = lambda: str(tmp_path / "other.sock")
    with pytest.raises(gateway.GatewayError, match="exact configured"):
        gateway.validate_listener(config, listener)
    listener.getsockname = lambda: str(config.listen_socket)
    listener.getsockopt = lambda *args: 0
    with pytest.raises(gateway.GatewayError, match="exact configured"):
        gateway.validate_listener(config, listener)
