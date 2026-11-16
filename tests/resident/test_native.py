"""Real native children, with host ownership/mount probes emulated explicitly.

These prove the launcher protocol. They do not qualify an installed OpenCode
binary, a provider, systemd containment or the gateway credential boundary.
"""
from __future__ import annotations

import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import socketserver
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

import pytest

from lanectl import resident_native as native
from lanectl.resident import ResidentError


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def context_bytes():
    value = {
        "schema": "resident-context/v1", "status": "ready", "authorizes_effects": False,
        "scope": {"resident": "writer-one", "project": "stories", "branch": "canon"},
        "budget": {"max_bytes": 65536, "max_tokens": None, "token_measurement": "not-measured"},
        "source_refs": [], "blockers": [], "omissions": [],
        "sections": [{"kind": key, "items": []} for key in
                     ("instructions", "current_work", "required_sources", "orientation", "memories", "worker_outputs")],
    }
    value["sections"][0]["items"] = [{"id": "instructions", "content": "Write the admitted story."}]
    value["sections"][1]["items"] = [{"id": "current_work", "content": {"next_action": "draft chapter one"}}]
    value["digest"] = digest(encode(value))
    return encode(value)


CHILD = '''import json, os, pathlib, sys
if "--version" in sys.argv:
    print("2.2.3")
    sys.exit(0)
workspace = pathlib.Path.cwd()
attached = pathlib.Path(sys.argv[sys.argv.index("--file") + 1]).read_bytes()
(workspace / "observed.json").write_text(json.dumps({"argv": sys.argv[1:], "env": dict(os.environ),
    "context": attached.decode(), "pgid": os.getpgrp()}))
(workspace / "drafts").mkdir(exist_ok=True)
(workspace / "drafts/story.txt").write_text("The bridge remembers.\\n")
result = {"schema": "lanectl.resident-result/v1", "episode_id": os.environ["LANECTL_RESIDENT_EPISODE"],
          "generation": int(os.environ["LANECTL_RESIDENT_GENERATION"]), "stop_reason": "completed",
          "artifacts": ["drafts/story.txt"], "continuation": {"next_action": "revise"}}
pathlib.Path(os.environ["LANECTL_RESIDENT_RESULT"]).write_text(json.dumps(result))
print(json.dumps({"type": "text", "part": {"text": "Done"}}))
'''


@pytest.fixture
def setup(tmp_path, monkeypatch):
    # Host-specific facts are not available in an unprivileged unit test.
    monkeypatch.setattr(native, "assert_protected_file", lambda path: None)
    monkeypatch.setattr(native, "_require_readonly_config", lambda path: None)
    monkeypatch.setattr(native, "_managed_system_config_present", lambda: False)
    monkeypatch.setattr(native, "_protected_directory", lambda path: None)
    monkeypatch.setattr(native, "_validate_gateway_socket", lambda path: None)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".lanectl-resident-results").mkdir()
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    config_dir = tmp_path / "opencode"
    config_dir.mkdir()
    executable = tmp_path / "opencode-bin"
    profile = tmp_path / "native.json"
    packet = context_bytes()
    environment = {
        "LANECTL_RESIDENT_EPISODE": "ep-native-test", "LANECTL_RESIDENT_GENERATION": "7",
        "LANECTL_RESIDENT_CONTEXT_SHA256": digest(packet),
        "LANECTL_RESIDENT_RESULT": str(workspace / ".lanectl-resident-results/ep-native-test.json"),
        "OPENAI_API_KEY": "never-forward", "OPENCODE_CONFIG_CONTENT": "never-forward",
        "HTTP_PROXY": "http://never-forward", "PATH": "/evil/path", "PYTHONPATH": "/evil/python",
        "HOME": "/home/regular-user", "XDG_DATA_HOME": "/home/regular-user/auth",
    }
    raw = {
        "schema": "lanectl.resident-native/v1", "resident_id": "writer-one",
        "route": "opencode-go/deepseek-v4.1-flash", "workspace": str(workspace),
        "context_scope": {"resident": "writer-one", "project": "stories", "branch": "canon"},
        "artifact_roots": ["drafts", "canon"], "gateway_base_url": "http://127.0.0.1:18021/v1",
        "gateway_socket": None,
        "opencode_executable": str(executable), "opencode_sha256": "0" * 64,
        "opencode_config": str(config_dir / "opencode.json"), "opencode_config_sha256": "0" * 64,
        "runtime_root": str(runtime), "timeout_s": 3, "max_output_bytes": 32768,
        "context_tokens": 32768, "output_tokens": 4096, "tool_path": ["/usr/bin", "/bin"],
    }

    def configure(*, script=CHILD, **changes):
        raw.update(changes)
        executable.unlink(missing_ok=True)
        executable.write_text(f"#!{sys.executable}\n" + script)
        executable.chmod(0o500)
        raw["opencode_sha256"] = digest(executable.read_bytes())
        config_bytes = encode(native.render_config(raw)) + b"\n"
        Path(raw["opencode_config"]).write_bytes(config_bytes)
        raw["opencode_config_sha256"] = digest(config_bytes)
        profile.write_bytes(encode(raw))
        return raw

    configure()
    return {"workspace": workspace, "runtime": runtime, "profile": profile, "raw": raw,
            "packet": packet, "environment": environment, "configure": configure}


def run(s):
    return native.run(s["profile"], s["packet"], environ=s["environment"])


@pytest.mark.parametrize("route,model", [
    ("opencode-go/deepseek-v4.1-flash", "deepseek-v4.1-flash"),
    ("local/worker-fast", "worker-fast"),
])
def test_single_explicit_provider_and_no_fallback(setup, route, model):
    raw = setup["configure"](route=route)
    value = native.render_config(raw)
    assert value["model"] == f"resident-gateway/{model}"
    assert set(value["providers"]) == {"resident-gateway"}
    provider = value["providers"]["resident-gateway"]
    assert provider["settings"]["baseURL"] == "http://127.0.0.1:18021/v1"
    assert provider["settings"]["apiKey"] == "resident-gateway"
    assert provider["headers"]["x-opencode-session"] == "{env:LANECTL_RESIDENT_EPISODE}"
    assert set(provider["models"]) == {model}
    assert value["mcp"] == {"servers": {}}
    assert value["plugins"] == []
    assert {"action": "provider.use", "resource": "*", "effect": "deny"} in value["policies"]


def test_real_child_receives_exact_context_clean_environment_and_result(setup):
    outcome = run(setup)
    assert outcome["stop_reason"] == "completed"
    assert outcome["artifacts"] == ["drafts/story.txt"]
    observed = json.loads((setup["workspace"] / "observed.json").read_text())
    assert observed["context"].encode() == setup["packet"]
    assert "--standalone" in observed["argv"] and "--auto" in observed["argv"]
    assert observed["argv"][observed["argv"].index("--model") + 1] == "resident-gateway/deepseek-v4.1-flash"
    assert observed["pgid"] == os.getpgrp()  # retain the outer owner's cleanup boundary
    env = observed["env"]
    for name in ("OPENAI_API_KEY", "HTTP_PROXY", "OPENCODE_CONFIG_CONTENT", "PYTHONPATH"):
        assert name not in env
    assert env["HOME"].startswith(str(setup["runtime"]) + "/")
    assert env["PATH"] != "/evil/path"
    assert env["LANECTL_RESIDENT_CONTEXT_SHA256"] == digest(setup["packet"])
    assert env["OPENCODE_DISABLE_PROJECT_CONFIG"] == "1"
    assert not list(setup["runtime"].iterdir())


@pytest.mark.parametrize("url", [
    "http://localhost:18021/v1", "https://example.com/v1", "http://127.0.0.1/v1",
    "http://127.0.0.1:18021/v1?url=https://example.com", "http://token@127.0.0.1:18021/v1",
    "http://127.0.0.1:18021/v1#fragment", "http://127.0.0.1:18021/other",
])
def test_endpoint_cannot_select_an_unqualified_destination(setup, url):
    with pytest.raises(ResidentError, match="loopback|gateway"):
        native.render_config(dict(setup["raw"], gateway_base_url=url))


@pytest.mark.parametrize("route", ["deepseek-4.1-flash", "opencode-go/other", "local/auto", "openai/paid"])
def test_route_has_no_alias_or_paid_fallback(setup, route):
    with pytest.raises(ResidentError, match="route"):
        native.render_config(dict(setup["raw"], route=route))


def test_context_integrity_failure_precedes_native_launch(setup):
    setup["environment"]["LANECTL_RESIDENT_CONTEXT_SHA256"] = "0" * 64
    with pytest.raises(ResidentError, match="context.*digest"):
        run(setup)
    assert not (setup["workspace"] / "observed.json").exists()


def test_unready_context_is_refused_even_when_file_hash_matches(setup):
    value = json.loads(setup["packet"])
    value["status"] = "blocked"
    value.pop("digest")
    value["digest"] = digest(encode(value))
    setup["packet"] = encode(value)
    setup["environment"]["LANECTL_RESIDENT_CONTEXT_SHA256"] = digest(setup["packet"])
    with pytest.raises(ResidentError, match="context"):
        run(setup)


def test_config_is_not_trusted_from_chmod_or_writable_mount(setup, monkeypatch):
    def refuse(_):
        raise ResidentError("native configuration must be mounted read-only")
    monkeypatch.setattr(native, "_require_readonly_config", refuse)
    with pytest.raises(ResidentError, match="read-only"):
        run(setup)
    assert not (setup["workspace"] / "observed.json").exists()


def test_ownership_is_checked_for_all_executable_inputs(setup, monkeypatch):
    seen = []
    monkeypatch.setattr(native, "assert_protected_file", lambda path: seen.append(Path(path)))
    run(setup)
    assert set(seen) >= {setup["profile"], Path(setup["raw"]["opencode_executable"]),
                         Path(setup["raw"]["opencode_config"])}


def test_valid_hash_cannot_authorize_extra_provider_or_plugins(setup):
    path = Path(setup["raw"]["opencode_config"])
    value = json.loads(path.read_bytes())
    value["providers"]["openai"] = {"settings": {"apiKey": "unexpected"}}
    path.write_bytes(encode(value))
    setup["raw"]["opencode_config_sha256"] = digest(path.read_bytes())
    setup["profile"].write_bytes(encode(setup["raw"]))
    with pytest.raises(ResidentError, match="configuration.*match"):
        run(setup)


def test_inherited_managed_configuration_is_refused(setup, monkeypatch):
    monkeypatch.setattr(native, "_managed_system_config_present", lambda: True)
    with pytest.raises(ResidentError, match="managed|system"):
        run(setup)


def test_writable_or_relative_tool_directory_cannot_be_inherited(setup, monkeypatch):
    with pytest.raises(ResidentError, match="absolute"):
        native.render_config(dict(setup["raw"], tool_path=["."]))
    with pytest.raises(ResidentError, match="writable workspace"):
        native.render_config(dict(setup["raw"], tool_path=[str(setup["workspace"])]))
    def refuse(_):
        raise ResidentError("tool_path must be root-protected")
    monkeypatch.setattr(native, "_protected_directory", refuse)
    with pytest.raises(ResidentError, match="root-protected"):
        run(setup)
    assert not (setup["workspace"] / "observed.json").exists()


def test_duplicate_or_nonfinite_result_json_is_not_accepted(setup):
    replacement = 'json.dumps(result).replace(\'"generation": 7\', \'"generation": 7, "generation": 7\')'
    setup["configure"](script=CHILD.replace(".write_text(json.dumps(result))", f".write_text({replacement})"))
    with pytest.raises(ResidentError, match="duplicate"):
        run(setup)


def test_context_larger_than_single_argv_limit_is_attached_without_truncation(setup):
    value = json.loads(setup["packet"])
    value["sections"][0]["items"][0]["content"] = "A" * 160000
    value["budget"]["max_bytes"] = 200000
    value.pop("digest")
    value["digest"] = digest(encode(value))
    setup["packet"] = encode(value)
    setup["environment"]["LANECTL_RESIDENT_CONTEXT_SHA256"] = digest(setup["packet"])
    assert run(setup)["stop_reason"] == "completed"
    observed = json.loads((setup["workspace"] / "observed.json").read_text())
    assert observed["context"].encode() == setup["packet"]
    assert max(map(len, observed["argv"])) < 5000


@pytest.mark.parametrize("version", ["1.19.0", "2.2.2", "3.0.0", "unrecognized"])
def test_unqualified_schema_version_cannot_run(setup, version):
    setup["configure"](script=CHILD.replace('print("2.2.3")', f'print({version!r})'))
    with pytest.raises(ResidentError, match="OpenCode|version|schema"):
        run(setup)
    assert not (setup["workspace"] / "observed.json").exists()


@pytest.mark.parametrize("replacement", [
    'result["generation"] = 8', 'result["generation"] = True',
    'result["episode_id"] = "ep-other"', 'result["stop_reason"] = "accepted"',
    'result["schema"] = "unknown/v1"', 'result["extra"] = "unknown"',
    'result["artifacts"] = ["../outside"]', 'result["artifacts"] = ["observed.json"]',
    'result["artifacts"] = ["drafts/missing.txt"]',
    'result["artifacts"] = ["drafts/story.txt", "drafts/story.txt"]',
])
def test_result_contract_and_artifacts_are_checked_before_success(setup, replacement):
    setup["configure"](script=CHILD.replace('pathlib.Path(os.environ["LANECTL_RESIDENT_RESULT"])',
                                           replacement + '\npathlib.Path(os.environ["LANECTL_RESIDENT_RESULT"])'))
    with pytest.raises((ResidentError, OSError, ValueError)):
        run(setup)


def test_symlink_artifact_cannot_escape_workspace(setup):
    setup["configure"](script=CHILD.replace(
        '(workspace / "drafts/story.txt").write_text("The bridge remembers.\\n")',
        '(workspace / "drafts/story.txt").symlink_to("/etc/passwd")'))
    with pytest.raises((ResidentError, OSError)):
        run(setup)


def test_nonzero_native_exit_cannot_be_hidden_by_completed_result(setup):
    setup["configure"](script=CHILD + "\nsys.exit(9)\n")
    with pytest.raises(ResidentError, match="exit.*9"):
        run(setup)


def test_result_path_cannot_be_redirected_and_old_result_cannot_be_replayed(setup):
    expected = setup["environment"]["LANECTL_RESIDENT_RESULT"]
    setup["environment"]["LANECTL_RESIDENT_RESULT"] = str(setup["workspace"] / "unassigned.json")
    with pytest.raises(ResidentError, match="result.*path"):
        run(setup)
    setup["environment"]["LANECTL_RESIDENT_RESULT"] = expected
    Path(expected).write_text("{}")
    with pytest.raises(ResidentError, match="already|existing|replay"):
        run(setup)


def test_timeout_stops_native_child_and_reports_failure(setup):
    setup["configure"](script=CHILD + "\nimport time\ntime.sleep(30)\n", timeout_s=.2)
    start = time.monotonic()
    with pytest.raises(ResidentError, match="timeout"):
        run(setup)
    assert time.monotonic() - start < 3


def test_stdout_flood_is_bounded_in_memory_and_does_not_report_success(setup):
    setup["configure"](script=CHILD + "\nsys.stdout.write('x' * 1000000)\n", max_output_bytes=4096)
    with pytest.raises(ResidentError, match="output.*bound|output.*limit"):
        run(setup)


def test_render_command_is_read_only_and_does_not_need_host_qualification(setup, monkeypatch, capsys):
    monkeypatch.setattr(native, "assert_protected_file", lambda path: pytest.fail("render is not execution"))
    code = native.main(["render-config", "--config", str(setup["profile"])])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["model"] == "resident-gateway/deepseek-v4.1-flash"
    assert not (setup["workspace"] / "observed.json").exists()


@pytest.fixture(params=("emulated", "unix"))
def unix_gateway(tmp_path, monkeypatch, request):
    class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True

    calls = []
    response = {"status": 200, "type": "application/json", "body": b'{"data":[{"id":"deepseek-v4.1-flash"}]}',
                "drop": False}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_GET(self):
            self.reply()

        def do_POST(self):
            self.reply()

        def reply(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            calls.append({"path": self.path, "headers": dict(self.headers), "body": body})
            self.send_response(response["status"])
            self.send_header("Content-Type", response["type"])
            self.send_header("Content-Length", str(len(response["body"]) + (10 if response["drop"] else 0)))
            self.send_header("Location", "https://never-follow.invalid")
            self.send_header("Set-Cookie", "never-forward=this")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                self.wfile.write(response["body"])
            except (BrokenPipeError, ConnectionResetError):
                pass
            self.close_connection = True

    # sockaddr_un.sun_path is short; pytest's descriptive directory names are not.
    directory = tempfile.TemporaryDirectory(prefix="resident-gateway-")
    path = Path(directory.name) / "gateway.sock"
    if request.param == "unix":
        try:
            server = Server(str(path), Handler)
        except PermissionError:
            directory.cleanup()
            pytest.skip("executor denies AF_UNIX; TCP-emulated relay cases still run")
    else:
        # Only the socket syscall boundary is emulated. The real relay still
        # selects and connects its one configured path, then parses/streams HTTP.
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        class MappedUnixSocket(socket.socket):
            def __init__(self):
                super().__init__(socket.AF_INET, socket.SOCK_STREAM)

            def connect(self, address):
                assert address == str(path)
                return super().connect(("127.0.0.1", server.server_port))
        monkeypatch.setattr(native, "_new_gateway_socket", MappedUnixSocket)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield path, calls, response
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
    directory.cleanup()


def relay_request(path="/v1/models", *, data=None, headers=None):
    request = urllib.request.Request("http://127.0.0.1:18021" + path, data=data, headers=headers or {})
    with urllib.request.urlopen(request, timeout=3) as response:
        return response.status, response.headers, response.read()


def test_unix_relay_rejects_mutable_socket_and_alternate_listener_configuration(setup):
    for path in (str(setup["workspace"] / "gateway.sock"), str(setup["runtime"] / "gateway.sock"), "relative.sock"):
        with pytest.raises(ResidentError, match="socket|absolute"):
            native.render_config(dict(setup["raw"], gateway_socket=path))
    with pytest.raises(ResidentError, match="18021|relay"):
        native.render_config(dict(setup["raw"], gateway_socket="/run/protected/model.sock",
                                  gateway_base_url="http://127.0.0.1:18022/v1"))


def test_unix_relay_forwards_only_fixed_gateway_methods_and_no_client_secrets(setup, unix_gateway):
    path, calls, response = unix_gateway
    raw = setup["configure"](gateway_socket=str(path))
    with native.gateway_relay(raw):
        status, headers, body = relay_request(headers={"Authorization": "Bearer never-forward", "X-Upstream": "evil"})
        assert status == 200 and body == response["body"]
        assert "Location" not in headers and "Set-Cookie" not in headers
        forwarded = {name.lower(): value for name, value in calls[-1]["headers"].items()}
        assert "authorization" not in forwarded and "x-upstream" not in forwarded
        for endpoint in ("/v1/embeddings", "/v1/models?upstream=evil", "http://evil.invalid/v1/models"):
            with pytest.raises(urllib.error.HTTPError) as exc:
                relay_request(endpoint)
            assert exc.value.code in (400, 404)
        assert len(calls) == 1
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", 18021), timeout=.1)


def test_unix_relay_preserves_streaming_and_native_function_calls(setup, unix_gateway):
    path, calls, response = unix_gateway
    raw = setup["configure"](gateway_socket=str(path))
    response.update(type="text/event-stream", body=b'data: {"choices":[{"delta":{"tool_calls":[]}}]}\n\ndata: [DONE]\n\n')
    payload = {"model": "deepseek-v4.1-flash", "messages": [{"role": "user", "content": "write"}],
               "stream": True, "tools": [{"type": "function", "function": {"name": "shell"}}]}
    with native.gateway_relay(raw):
        status, _, body = relay_request("/v1/chat/completions", data=encode(payload), headers={"Content-Type": "application/json"})
        assert status == 200 and body == response["body"]
        forwarded = json.loads(calls[-1]["body"])
        assert forwarded["tools"] == payload["tools"] and forwarded["max_tokens"] == raw["output_tokens"]
        with pytest.raises(urllib.error.HTTPError) as exc:
            relay_request("/v1/chat/completions", data=encode(dict(payload, model="paid-fallback")),
                          headers={"Content-Type": "application/json"})
        assert exc.value.code == 400
    assert len(calls) == 1


@pytest.mark.parametrize("change", [
    {"status": 302}, {"drop": True}, {"type": "text/event-stream", "body": b'data: {"partial":true}\n\n'},
])
def test_unix_relay_does_not_turn_redirect_or_incomplete_gateway_reply_into_success(setup, unix_gateway, change):
    path, _, response = unix_gateway
    raw = setup["configure"](gateway_socket=str(path))
    response.update(change)
    with native.gateway_relay(raw):
        with pytest.raises((urllib.error.HTTPError, http.client.IncompleteRead, ConnectionResetError)):
            relay_request()


def test_native_child_can_use_unix_gateway_relay_for_entire_episode(setup, unix_gateway):
    path, calls, _ = unix_gateway
    extra = '''import urllib.request
with urllib.request.urlopen("http://127.0.0.1:18021/v1/models", timeout=2) as reply:
    assert reply.status == 200
'''
    setup["configure"](gateway_socket=str(path), script=CHILD + extra)
    assert run(setup)["stop_reason"] == "completed"
    assert calls and calls[0]["path"] == "/v1/models"


def test_unix_relay_output_bound_is_an_http_failure(setup, unix_gateway, monkeypatch):
    path, _, response = unix_gateway
    raw = setup["configure"](gateway_socket=str(path))
    monkeypatch.setattr(native, "RELAY_RESPONSE_BYTES", 1024)
    response.update(body=b"x" * 2048)
    with native.gateway_relay(raw):
        with pytest.raises((urllib.error.HTTPError, http.client.IncompleteRead, ConnectionResetError)):
            relay_request()


def test_relay_shutdown_interrupts_a_partially_received_request(setup, unix_gateway):
    path, _, _ = unix_gateway
    raw = setup["configure"](gateway_socket=str(path))
    with native.gateway_relay(raw):
        client = socket.create_connection(("127.0.0.1", 18021), timeout=2)
        client.sendall(b"POST /v1/chat/completions HTTP/1.1\r\nHost: local\r\n")
        # Allow the accept loop to register the handler before exercising abort.
        time.sleep(.05)
    try:
        assert client.recv(1) == b""
    except ConnectionResetError:
        pass
    finally:
        client.close()
