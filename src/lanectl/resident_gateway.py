"""A separately owned fixed model capability for native resident harnesses.

The worker sees a loopback OpenAI-compatible endpoint and no upstream secret.
Host firewall/UID isolation restricts who can reach it. This is not an Internet
proxy, a model router, a tokenizer, or a claim about subscription entitlement.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import ssl
import stat
import struct
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import uuid

from .resident import assert_protected_file


GO_ROUTE = "opencode-go/deepseek-v4.1-flash"
LOCAL_ROUTE = "local/worker-fast"
GO_BASE = "https://opencode.ai/inference/go/openai/v1"
ANTHROPIC_ROUTE = "anthropic-api/claude-haiku-5-5"
ANTHROPIC_BASE = "https://api.anthropic.com/v1"
ANTHROPIC_EXCHANGE = ANTHROPIC_BASE + "/oauth/token"
USER_AGENT = "lanectl-resident/0.2 native-opencode-gateway"


class GatewayError(ValueError):
    pass


class RateLimited(GatewayError):
    pass


def _json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise GatewayError("duplicate JSON object key")
            result[key] = value
        return result

    def invalid_constant(value):
        raise GatewayError("non-finite JSON number")

    try:
        return json.loads(data, object_pairs_hook=unique, parse_constant=invalid_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise GatewayError("invalid JSON") from exc


def _bounded_int(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise GatewayError(f"{name} is outside its integer bound")
    return value


@dataclass(frozen=True)
class GatewayConfig:
    route: str
    upstream_base_url: str
    listen_port: int
    credential_name: str
    session_id: str
    state_file: Path
    listen_socket: Path | None = None
    ca_file: Path | None = None
    max_request_bytes: int = 512 * 1024
    max_response_bytes: int = 8 * 1024 * 1024
    max_output_tokens: int = 8192
    timeout_s: int = 900
    max_requests_per_window: int | None = None
    window_s: int = 3600

    @property
    def model(self):
        return self.route.split("/", 1)[1]


def validate_config(raw):
    fields = {"schema", "route", "upstream_base_url", "listen_port", "credential_name",
              "session_id", "state_file", "ca_file", "max_request_bytes", "max_response_bytes",
              "max_output_tokens", "timeout_s", "max_requests_per_window", "window_s", "listen_socket"}
    if (not isinstance(raw, dict) or raw.get("schema") != "lanectl.resident-gateway/v1"
            or set(raw) - fields):
        raise GatewayError("invalid gateway configuration schema or unknown field")
    route = raw.get("route")
    if route not in (GO_ROUTE, LOCAL_ROUTE, ANTHROPIC_ROUTE):
        raise GatewayError("select one supported fixed resident route")
    origin = raw.get("upstream_base_url")
    if not isinstance(origin, str):
        raise GatewayError("an explicit upstream origin is required")
    try:
        parsed = urlsplit(origin)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path.rstrip("/") != (
                    "/inference/go/openai/v1" if route == GO_ROUTE else "/v1")
                or any(ord(char) <= 32 for char in origin)):
            raise GatewayError("upstream must be one explicit verified HTTPS model API")
        if parsed.port is not None:
            _bounded_int(parsed.port, 1, 65535, "upstream port")
    except ValueError as exc:
        raise GatewayError("invalid upstream origin") from exc
    origin = origin.rstrip("/")
    if route == GO_ROUTE and origin != GO_BASE:
        raise GatewayError("Go requires the exact subscription endpoint; no paid fallback")
    if route == ANTHROPIC_ROUTE and origin != ANTHROPIC_BASE:
        raise GatewayError("Anthropic requires the exact Messages API origin")
    credential = raw.get("credential_name", "upstream-token")
    if not isinstance(credential, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", credential) is None:
        raise GatewayError("invalid systemd credential name")
    session = raw.get("session_id")
    if not isinstance(session, str) or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", session) is None:
        raise GatewayError("a stable bounded resident session_id is required")
    state = raw.get("state_file")
    if not isinstance(state, str) or not Path(state).is_absolute():
        raise GatewayError("state_file must be an absolute protected service path")
    ca = raw.get("ca_file")
    if ca is not None and (not isinstance(ca, str) or not Path(ca).is_absolute()):
        raise GatewayError("ca_file must be an absolute certificate path")
    listener = raw.get("listen_socket")
    if listener is not None and (not isinstance(listener, str) or not Path(listener).is_absolute()
            or str(Path(listener)) != listener or ".." in Path(listener).parts
            or len(listener.encode("utf-8")) > 107 or any(ord(c) < 32 for c in listener)):
        raise GatewayError("listen_socket must be a bounded absolute filesystem socket path")
    limit = raw.get("max_requests_per_window")
    if limit is not None:
        _bounded_int(limit, 1, 100000, "max_requests_per_window")
    if route in (GO_ROUTE, ANTHROPIC_ROUTE) and limit is None:
        raise GatewayError("commercial routes require an explicit persistent request allowance")
    return GatewayConfig(
        route=route, upstream_base_url=origin,
        listen_port=_bounded_int(raw.get("listen_port", 18021), 1024, 65535, "listen_port"),
        credential_name=credential, session_id=session, state_file=Path(state),
        listen_socket=Path(listener) if listener else None,
        ca_file=Path(ca) if ca else None,
        max_request_bytes=_bounded_int(raw.get("max_request_bytes", 512 * 1024), 1024, 2 * 1024 * 1024, "max_request_bytes"),
        max_response_bytes=_bounded_int(raw.get("max_response_bytes", 8 * 1024 * 1024), 1024, 16 * 1024 * 1024, "max_response_bytes"),
        max_output_tokens=_bounded_int(raw.get("max_output_tokens", 8192), 1, 8192, "max_output_tokens"),
        timeout_s=_bounded_int(raw.get("timeout_s", 900), 1, 900, "timeout_s"),
        max_requests_per_window=limit,
        window_s=_bounded_int(raw.get("window_s", 3600), 60, 86400, "window_s"))


def load_config(path):
    assert_protected_file(path)
    data = Path(path).read_bytes()
    if len(data) > 64 * 1024:
        raise GatewayError("gateway configuration is too large")
    config = validate_config(_json(data))
    if config.ca_file:
        assert_protected_file(config.ca_file)
    return config


def _systemd_credential_acl(fd, info, directory):
    # With a static service UID, systemd can expose a root-owned credential
    # using a named read-only ACL. The group mode then shows the ACL mask.
    if (Path(directory).parent != Path("/run/credentials")
            or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (0, 0, 0o440)):
        return False
    undefined_id = 0xffffffff
    expected = struct.pack("<I", 2) + b"".join(
        struct.pack("<HHI", tag, permissions, user)
        for tag, permissions, user in (
            (0x01, 4, undefined_id),  # owner
            (0x02, 4, os.geteuid()),  # named service UID
            (0x04, 0, undefined_id),  # owning group
            (0x10, 4, undefined_id),  # mask
            (0x20, 0, undefined_id),  # other
        )
    )
    try:
        return os.getxattr(fd, "system.posix_acl_access") == expected
    except OSError:
        return False


def read_credential(name, environment=None, *, appservice_directory: Path | None = None):
    if not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) is None:
        raise GatewayError("invalid credential name")
    directory = (str(appservice_directory) if appservice_directory is not None
                 else (os.environ if environment is None else environment).get("CREDENTIALS_DIRECTORY", ""))
    if not directory or not Path(directory).is_absolute():
        raise GatewayError("absolute credentials directory is required")
    parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            info = os.fstat(fd)
            private = info.st_uid in (0, os.geteuid()) and not info.st_mode & 0o077
            if appservice_directory is None:
                permitted = private or _systemd_credential_acl(fd, info, directory)
            else:
                # The Secret key is a read-only subPath mount in the gateway
                # container. The owning group is the pod's dedicated fsGroup.
                group_readable = (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (
                    0, os.getegid(), 0o440)
                permitted = bool(os.fstatvfs(fd).f_flag & os.ST_RDONLY) and (private or group_readable)
            if (not stat.S_ISREG(info.st_mode)
                    or not permitted):
                raise GatewayError("upstream credential must be a private regular file")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                data = stream.read(8193)
            if len(data) > 8192:
                raise GatewayError("upstream credential exceeds its bound")
        finally:
            os.close(fd)
    finally:
        os.close(parent)
    try:
        token = data.decode("ascii").strip()
    except UnicodeError as exc:
        raise GatewayError("invalid upstream credential") from exc
    if not token or any(ord(char) < 33 or ord(char) > 126 for char in token):
        raise GatewayError("invalid upstream credential")
    return token


def normalize_request(config, data):
    if len(data) > config.max_request_bytes:
        raise GatewayError("request body exceeds byte bound")
    body = _json(data)
    allowed = {"model", "messages", "tools", "tool_choice", "parallel_tool_calls", "temperature",
               "top_p", "presence_penalty", "frequency_penalty", "max_tokens", "max_completion_tokens",
               "stream", "stream_options", "stop", "seed", "response_format", "reasoning_effort",
               "n", "store", "user"}
    if not isinstance(body, dict) or set(body) - allowed or body.get("model") != config.model:
        raise GatewayError("request must target the one configured model and supported chat fields")
    if body.get("n", 1) != 1 or type(body.get("n", 1)) is not int:
        raise GatewayError("one completion per request is required")
    if "store" in body and body["store"] is not False:
        raise GatewayError("remote response storage is disabled")
    if "stream" in body and type(body["stream"]) is not bool:
        raise GatewayError("stream must be a boolean")
    if "tools" in body:
        tools = body["tools"]
        if (not isinstance(tools, list) or len(tools) > 128
                or any(not isinstance(tool, dict) or set(tool) != {"type", "function"}
                       or tool["type"] != "function" or not isinstance(tool["function"], dict)
                       or not isinstance(tool["function"].get("name"), str) for tool in tools)):
            raise GatewayError("only native function tool declarations are allowed")
    choice = body.get("tool_choice")
    if choice is not None and choice not in ("auto", "none", "required"):
        if (not isinstance(choice, dict) or set(choice) != {"type", "function"}
                or choice["type"] != "function" or not isinstance(choice["function"], dict)
                or set(choice["function"]) != {"name"} or not isinstance(choice["function"]["name"], str)):
            raise GatewayError("only native function tool choice is allowed")
    limits = [key for key in ("max_tokens", "max_completion_tokens") if key in body]
    if len(limits) > 1:
        raise GatewayError("select only one output token bound")
    if limits:
        _bounded_int(body[limits[0]], 1, config.max_output_tokens, limits[0])
    else:
        body["max_tokens"] = config.max_output_tokens
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages or len(messages) > 4096:
        raise GatewayError("a bounded nonempty message list is required")
    for message in messages:
        if (not isinstance(message, dict) or message.get("role") not in
                ("system", "developer", "user", "assistant", "tool")):
            raise GatewayError("invalid chat message")
        if "tool_calls" in message:
            calls = message["tool_calls"]
            if (message["role"] != "assistant" or not isinstance(calls, list) or len(calls) > 128
                    or any(not isinstance(call, dict) or call.get("type") != "function"
                           or not isinstance(call.get("id"), str) or not isinstance(call.get("function"), dict)
                           or not isinstance(call["function"].get("name"), str)
                           or not isinstance(call["function"].get("arguments"), str) for call in calls)):
                raise GatewayError("only native function call messages are allowed")
        content = message.get("content")
        if content is None and message.get("role") == "assistant" and message.get("tool_calls"):
            continue
        if isinstance(content, str):
            continue
        if isinstance(content, list) and all(isinstance(part, dict) and set(part) == {"type", "text"}
                and part["type"] == "text" and isinstance(part["text"], str) for part in content):
            continue
        raise GatewayError("resident routes accept text and native function calls only")
    try:
        return json.dumps(body, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise GatewayError("invalid JSON value or UTF-8 text") from exc


def normalize_messages_request(config, data):
    """Accept native text and client-side tools on the fixed Messages route."""
    if len(data) > config.max_request_bytes:
        raise GatewayError("request body exceeds byte bound")
    body = _json(data)
    fields = {"model", "messages", "system", "tools", "tool_choice", "max_tokens", "stream", "thinking"}
    if not isinstance(body, dict) or set(body) - fields or body.get("model") != config.model:
        raise GatewayError("request must target the configured Messages model")
    _bounded_int(body.get("max_tokens"), 1, config.max_output_tokens, "max_tokens")
    if type(body.get("stream", False)) is not bool:
        raise GatewayError("stream must be a boolean")

    if body.pop("thinking", {"type": "disabled"}) not in (
            {"type": "disabled"},
            {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}},
    ):
        raise GatewayError("unsupported Messages thinking configuration")

    def has_valid_cache_control(block):
        return "cache_control" not in block or block["cache_control"] == {"type": "ephemeral"}

    def is_text(block):
        return (isinstance(block, dict) and not (set(block) - {"type", "text", "cache_control"})
                and block.get("type") == "text" and isinstance(block.get("text"), str)
                and has_valid_cache_control(block))

    system = body.get("system", "")
    if not isinstance(system, str) and not (
            isinstance(system, list) and all(is_text(block) for block in system)):
        raise GatewayError("system content must be text")
    tools = body.get("tools", [])
    if not isinstance(tools, list) or len(tools) > 128 or any(
            not isinstance(tool, dict) or set(tool) - {"name", "description", "input_schema", "cache_control"}
            or not has_valid_cache_control(tool)
            or not isinstance(tool.get("name"), str) or not isinstance(tool.get("input_schema"), dict)
            for tool in tools):
        raise GatewayError("only client-side tools are allowed")
    choice = body.get("tool_choice")
    if choice is not None and (not isinstance(choice, dict)
            or set(choice) - {"type", "name", "disable_parallel_tool_use"}
            or choice.get("type") not in ("auto", "none", "any", "tool")
            or ("name" in choice and choice["name"] not in [tool["name"] for tool in tools])):
        raise GatewayError("invalid tool choice")
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages or len(messages) > 4096:
        raise GatewayError("a bounded nonempty message list is required")
    for message in messages:
        if (not isinstance(message, dict) or set(message) != {"role", "content"}
                or message["role"] not in ("user", "assistant")):
            raise GatewayError("invalid Messages entry")
        role, content = message["role"], message["content"]
        if isinstance(content, str):
            continue
        if not isinstance(content, list) or not content:
            raise GatewayError("Messages content must be text or client-side tool blocks")
        for block in content:
            if is_text(block):
                continue
            if (role == "assistant" and isinstance(block, dict)
                    and set(block) == {"type", "id", "name", "input"} and block["type"] == "tool_use"
                    and isinstance(block["id"], str) and isinstance(block["name"], str)
                    and isinstance(block["input"], dict)):
                continue
            if (role == "user" and isinstance(block, dict)
                    and not (set(block) - {"type", "tool_use_id", "content", "is_error"})
                    and block.get("type") == "tool_result" and isinstance(block.get("tool_use_id"), str)
                    and type(block.get("is_error", False)) is bool):
                result = block.get("content", "")
                if isinstance(result, str) or (
                        isinstance(result, list) and all(is_text(part) for part in result)):
                    continue
            raise GatewayError("unsupported Messages content block")
    try:
        return json.dumps(body, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise GatewayError("invalid JSON value or UTF-8 text") from exc


class RequestLedger:
    """Reserve before network I/O; failed and uncertain requests remain spent."""
    def __init__(self, path):
        self.path = Path(path)
        directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(directory)
            if info.st_uid not in (0, os.geteuid()) or info.st_mode & 0o022:
                raise GatewayError("request ledger directory is not service-protected")
            try:
                fd = os.open(self.path.name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            except FileExistsError:
                try:
                    fd = os.open(self.path.name, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                except OSError as exc:
                    raise GatewayError("invalid request ledger file") from exc
            try:
                info = os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077):
                    raise GatewayError("request ledger must be a private regular service file")
            finally:
                os.close(fd)
        finally:
            os.close(directory)
        with self._connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise GatewayError("unsupported request ledger schema")
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, route TEXT NOT NULL, "
                       "reserved_at REAL NOT NULL, outcome TEXT NOT NULL, http_status INTEGER)")
            db.execute("CREATE INDEX IF NOT EXISTS requests_route_time ON requests(route, reserved_at)")
            db.execute("PRAGMA user_version=1")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    def reserve(self, route, limit, window_s, *, now=None):
        when = time.time() if now is None else now
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # Deliberately no upper timestamp bound: clock rollback must not
            # erase reservations already observed in the future.
            count = db.execute("SELECT count(*) FROM requests WHERE route=? AND reserved_at>?",
                               (route, when - window_s)).fetchone()[0]
            if limit is not None and count >= limit:
                raise RateLimited("configured request allowance exhausted")
            identifier = uuid.uuid4().hex
            db.execute("INSERT INTO requests VALUES (?, ?, ?, 'reserved', NULL)", (identifier, route, when))
        return identifier

    def finish(self, identifier, outcome, status):
        with self._connect() as db:
            db.execute("UPDATE requests SET outcome=?, http_status=? WHERE id=? AND outcome='reserved'",
                       (outcome, status, identifier))


class FixedHTTPS:
    """One explicit HTTPS connection, without redirects or proxy discovery.

Track the socket directly instead of reaching through urllib's private response
attributes. A deadline interrupts blocked header/body reads; each read also gets
only the remaining timeout. DNS/connect use the platform's bounded resolver and
socket connection behavior, which still need qualification on the target host.
"""
    def __init__(self, config, *, url=None):
        endpoint = "/messages" if config.route == ANTHROPIC_ROUTE else "/chat/completions"
        self.url = url or config.upstream_base_url + endpoint
        self.parsed = urlsplit(self.url)
        self.context = ssl.create_default_context(cafile=str(config.ca_file) if config.ca_file else None)

    def open(self, request, timeout):
        if request.full_url != self.url or request.get_method() != "POST":
            raise GatewayError("transport refuses a different destination or method")
        deadline = time.monotonic() + timeout
        connection = http.client.HTTPSConnection(self.parsed.hostname, self.parsed.port,
                                                timeout=timeout, context=self.context)
        timer = None
        try:
            connection.connect()
            sock = connection.sock

            def remaining():
                value = deadline - time.monotonic()
                if value <= 0:
                    raise TimeoutError("model request deadline reached")
                return value

            def abort():
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            timer = threading.Timer(remaining(), abort)
            timer.daemon = True
            timer.start()
            sock.settimeout(remaining())
            connection.request("POST", self.parsed.path, body=request.data,
                               headers=dict(request.header_items()))
            sock.settimeout(remaining())
            response = connection.getresponse()
            wrapped = FixedResponse(connection, response, sock, timer, deadline)
            if response.status != 200:
                # HTTPError is only a status carrier here. There is no redirect
                # handler and the body will be closed without reaching a client.
                raise urllib.error.HTTPError(self.url, response.status, "selected model unavailable",
                                             response.headers, wrapped)
            return wrapped
        except urllib.error.HTTPError:
            raise
        except BaseException:
            if timer:
                timer.cancel()
            connection.close()
            raise


class FixedResponse:
    def __init__(self, connection, response, sock, timer, deadline):
        self.connection, self.response, self.sock = connection, response, sock
        self.timer, self.deadline = timer, deadline
        self.status, self.headers = response.status, response.headers

    def read1(self, size):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("model request deadline reached")
        if self.response.isclosed():
            if self.response.length not in (None, 0):
                raise http.client.IncompleteRead(b"")
            return b""
        self.sock.settimeout(remaining)
        chunk = self.response.read1(size)
        if not chunk and self.response.length not in (None, 0):
            raise http.client.IncompleteRead(b"")
        if time.monotonic() >= self.deadline:
            raise TimeoutError("model request deadline reached")
        return chunk

    def close(self):
        self.timer.cancel()
        try:
            self.response.close()
        finally:
            self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def build_opener(config):
    return FixedHTTPS(config)


class BoundedServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    request_queue_size = 8

    def __init__(self, *args, **kwargs):
        self.connections = threading.BoundedSemaphore(8)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.connections.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.connections.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connections.release()


def validate_listener(config, listener):
    if (config.listen_socket is None or listener.family != socket.AF_UNIX
            or listener.type & 0xf != socket.SOCK_STREAM
            or listener.getsockname() != str(config.listen_socket)
            or listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) != 1):
        raise GatewayError("socket activation requires the exact configured listening Unix listener")


def activation_socket(config, environment=None):
    env = os.environ if environment is None else environment
    if env.get("LISTEN_PID") != str(os.getpid()) or env.get("LISTEN_FDS") != "1":
        raise GatewayError("exactly one systemd socket activation descriptor is required")
    try:
        listener = socket.socket(fileno=3)
    except OSError as exc:
        raise GatewayError("systemd socket activation descriptor is unavailable") from exc
    try:
        validate_listener(config, listener)
    except BaseException:
        listener.close()
        raise
    return listener


class BoundedUnixServer(BoundedServer):
    address_family = socket.AF_UNIX

    def __init__(self, config, handler, listener):
        validate_listener(config, listener)
        super().__init__(str(config.listen_socket), handler, bind_and_activate=False)
        self.socket.close()
        self.socket = listener
        self.server_name = "resident-model"
        self.server_port = 0
        # PID1 owns the filesystem entry and socket permissions. Closing this
        # process's descriptor must not unlink or replace that capability.


class AnthropicFederation:
    """Resolve the workspace bearer within the gateway's single-request lock."""

    def __init__(self, config, environment=None, *, opener=None):
        env = os.environ if environment is None else environment
        if config.route != ANTHROPIC_ROUTE or config.listen_socket is not None or config.listen_port != 18021:
            raise GatewayError("Claude federation requires the fixed appservice pilot route")
        if any(name in env for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
                                        "ANTHROPIC_PROFILE", "ANTHROPIC_IDENTITY_TOKEN")):
            raise GatewayError("Claude federation requires a projected token without credential overrides")
        self.token_file = Path(env.get("ANTHROPIC_IDENTITY_TOKEN_FILE", ""))
        if not self.token_file.is_absolute():
            raise GatewayError("Claude federation requires an absolute projected token path")
        self.exchange = {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer"}
        for field, pattern in (
            ("federation_rule_id", r"fdrl_[A-Za-z0-9_-]{1,128}"),
            ("organization_id", r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"),
            ("workspace_id", r"wrkspc_[A-Za-z0-9_-]{1,128}"),
            ("service_account_id", r"svac_[A-Za-z0-9_-]{1,128}"),
        ):
            value = env.get("ANTHROPIC_" + field.upper(), "")
            if not re.fullmatch(pattern, value):
                raise GatewayError("Claude federation identifiers are missing or malformed")
            self.exchange[field] = value
        self.opener = opener if opener is not None else FixedHTTPS(config, url=ANTHROPIC_EXCHANGE)
        self.token = ""
        self.refresh_at = 0.0

    def bearer(self):
        now = time.monotonic()
        if now < self.refresh_at:
            return self.token
        with self.token_file.open("rb") as source:
            raw_assertion = source.read(16385)
        assertion = raw_assertion.strip()
        if len(raw_assertion) > 16384 or not re.fullmatch(rb"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+){2}", assertion):
            raise GatewayError("invalid projected Claude identity token")
        request = urllib.request.Request(
            ANTHROPIC_EXCHANGE,
            data=json.dumps(dict(self.exchange, assertion=assertion.decode("ascii"))).encode(),
            method="POST",
            headers={"Content-Type": "application/json", "Accept-Encoding": "identity"},
        )
        try:
            with self.opener.open(request, timeout=15) as response:
                body = bytearray()
                while chunk := response.read1(16385 - len(body)):
                    body.extend(chunk)
                    if len(body) > 16384:
                        raise GatewayError("Claude federation response exceeds its byte bound")
        except urllib.error.HTTPError as exc:
            exc.close()
            raise GatewayError("Claude federation exchange refused") from None
        result = _json(body)
        if (not isinstance(result, dict) or result.get("token_type") != "Bearer"
                or result.get("scope") != "workspace:inference"):
            raise GatewayError("invalid Claude federation response")
        token = result.get("access_token")
        expires = result.get("expires_in")
        if (not isinstance(token, str) or not re.fullmatch(r"sk-ant-oat01-[A-Za-z0-9_-]{1,2048}", token)
                or type(expires) is not int or not 60 <= expires <= 600):
            raise GatewayError("invalid Claude federation token or lifetime")
        self.token = token
        self.refresh_at = now + expires - 30
        return token


class Gateway:
    def __init__(self, config, token, *, opener=None, federation=None):
        self.config, self.token = config, token
        self.federation = federation
        self.opener = build_opener(config) if opener is None else opener
        self.ledger = RequestLedger(config.state_file)
        self.inflight = threading.BoundedSemaphore(1)

    def make_server(self, *, activated_socket=None):
        app = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "resident-model"
            sys_version = ""

            def setup(self):
                super().setup()
                self.connection.settimeout(10)
                # Socket idle timeouts alone allow a slow drip to occupy all
                # client slots forever. Bound the entire header/body phase.
                self.request_timer = threading.Timer(10, self.abort_request)
                self.request_timer.daemon = True
                self.request_timer.start()

            def abort_request(self):
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            def finish(self):
                self.request_timer.cancel()
                super().finish()

            def log_message(self, *args):
                # Never log prompt bodies, native headers or upstream errors.
                pass

            def json_response(self, status, value):
                data = json.dumps(value, separators=(",", ":")).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                self.wfile.write(data)

            def error_response(self, status, message):
                self.json_response(status, {"error": {"message": message, "type": "resident_model_unavailable"}})

            def do_GET(self):
                self.request_timer.cancel()
                if self.path == "/healthz":
                    self.json_response(200, {"status": "live", "route": app.config.route,
                        "inference_readiness": "not-probed", "fallback": "none"})
                elif self.path == "/v1/models":
                    self.json_response(200, {"object": "list", "data": [{"id": app.config.model,
                        "object": "model", "owned_by": "configured-resident-route"}]})
                else:
                    self.error_response(404, "unsupported model endpoint")

            def do_POST(self):
                anthropic = app.config.route == ANTHROPIC_ROUTE
                endpoint = "/v1/messages" if anthropic else "/v1/chat/completions"
                if self.path != endpoint:
                    self.error_response(404, "unsupported model endpoint")
                    return
                try:
                    lengths = self.headers.get_all("Content-Length", [])
                    if (len(lengths) != 1 or len(lengths[0]) > 7 or not re.fullmatch(r"[0-9]+", lengths[0])
                            or self.headers.get("Transfer-Encoding") is not None
                            or self.headers.get_content_type() != "application/json"):
                        raise GatewayError("explicit JSON content length is required")
                    size = _bounded_int(int(lengths[0]), 1, app.config.max_request_bytes, "content length")
                    data = self.rfile.read(size)
                    if len(data) != size:
                        raise GatewayError("incomplete request body")
                    normalize = normalize_messages_request if anthropic else normalize_request
                    body = normalize(app.config, data)
                except (ValueError, OSError):
                    self.error_response(400, "invalid fixed-model request")
                    return
                self.request_timer.cancel()
                app.forward(self, body)

        if self.config.listen_socket:
            listener = activation_socket(self.config) if activated_socket is None else activated_socket
            return BoundedUnixServer(self.config, Handler, listener)
        if activated_socket is not None:
            raise GatewayError("TCP mode does not accept an activation socket")
        return BoundedServer(("127.0.0.1", self.config.listen_port), Handler)

    def forward(self, handler, body):
        if not self.inflight.acquire(blocking=False):
            handler.error_response(429, "resident model request already in flight")
            return
        reservation = None
        outcome, code, sent = "uncertain", None, False
        try:
            reservation = self.ledger.reserve(self.config.route, self.config.max_requests_per_window,
                                               self.config.window_s)
            anthropic = self.config.route == ANTHROPIC_ROUTE
            headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT,
                       "Accept-Encoding": "identity"}
            if anthropic:
                headers["anthropic-version"] = "2023-06-01"
                if self.federation is None:
                    headers["x-api-key"] = self.token
                else:
                    headers["Authorization"] = "Bearer " + self.federation.bearer()
            else:
                headers["Authorization"] = "Bearer " + self.token
            if self.config.route == GO_ROUTE:
                headers["x-opencode-session"] = self.config.session_id
            endpoint = "/messages" if anthropic else "/chat/completions"
            request = urllib.request.Request(self.config.upstream_base_url + endpoint,
                                             data=body, method="POST", headers=headers)
            deadline = time.monotonic() + self.config.timeout_s
            with self.opener.open(request, timeout=self.config.timeout_s) as response:
                content_type = response.headers.get_content_type()
                if response.status != 200 or content_type not in ("application/json", "text/event-stream"):
                    raise GatewayError("unsupported upstream response")
                handler.send_response(200)
                handler.send_header("Content-Type", content_type)
                handler.send_header("Transfer-Encoding", "chunked")
                handler.send_header("Connection", "close")
                handler.send_header("Cache-Control", "no-store")
                handler.end_headers()
                handler.close_connection = True
                sent = True
                total = 0
                tail = b""
                while True:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("model request deadline reached")
                    chunk = response.read1(min(65536, self.config.max_response_bytes - total + 1))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self.config.max_response_bytes:
                        raise GatewayError("upstream response exceeds byte bound")
                    tail = (tail + chunk)[-1024:]
                    handler.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                    handler.wfile.flush()
                marker = (rb'(?:^|\n)event: message_stop\r?\n'
                          rb'data:[ \t]*\{[ \t]*"type":[ \t]*"message_stop"[ \t]*\}[ \t\r\n]*$'
                          if anthropic else rb"(?:^|\n)data:[ \t]*\[DONE\][ \t\r\n]*$")
                if content_type == "text/event-stream" and re.search(marker, tail) is None:
                    raise GatewayError("upstream stream ended without its completion marker")
                # Only a complete, bounded response receives a terminal chunk.
                # A midstream error is an HTTP framing failure, never a clean
                # EOF-delimited 200 that a native client might accept.
                handler.wfile.write(b"0\r\n\r\n")
                handler.wfile.flush()
                outcome, code = "completed", 200
        except RateLimited:
            handler.error_response(429, "configured request allowance exhausted")
        except urllib.error.HTTPError as exc:
            code = exc.code
            outcome = "upstream-error"
            # No Location, upstream error body, cookies, authentication hints,
            # echoed credential, or alternate provider reach the native client.
            if not sent:
                handler.error_response(429 if exc.code == 429 else 502, "selected model unavailable")
            exc.close()
        except (OSError, GatewayError, sqlite3.Error, http.client.HTTPException):
            outcome = "unavailable"
            if not sent:
                handler.error_response(502, "selected model unavailable")
        finally:
            try:
                if reservation:
                    self.ledger.finish(reservation, outcome, code)
            finally:
                self.inflight.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "check-config"))
    parser.add_argument("--config", required=True, type=Path)
    credentials = parser.add_mutually_exclusive_group()
    credentials.add_argument("--appservice-credentials-directory", type=Path)
    credentials.add_argument("--anthropic-federation", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "check-config":
            config = validate_config(_json(args.config.read_bytes()))
            print(json.dumps({"schema": "lanectl.resident-gateway-check/v1", "route": config.route,
                              "model": config.model, "qualified": False, "fallback": "none"}))
            return 0
        config = load_config(args.config)
        if args.appservice_credentials_directory is not None and (
                config.route not in (GO_ROUTE, ANTHROPIC_ROUTE)
                or config.listen_socket is not None or config.listen_port != 18021):
            raise GatewayError("appservice credentials require the fixed loopback pilot route")
        if args.anthropic_federation:
            app = Gateway(config, None, federation=AnthropicFederation(config))
        else:
            app = Gateway(config, read_credential(config.credential_name,
                                                  appservice_directory=args.appservice_credentials_directory))
        with app.make_server() as server:
            server.serve_forever()
    except (OSError, ValueError, sqlite3.Error) as exc:
        # Configuration errors contain no secret or upstream response text.
        print(json.dumps({"schema": "lanectl.resident-gateway-error/v1", "error": type(exc).__name__}))
        return 2
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
