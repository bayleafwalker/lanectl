"""One native OpenCode resident episode through a fixed loopback gateway.

Provision the static OpenCode file with ``render-config --config SOURCE.json``;
then invoke ``run --config /etc/lanectl/resident-native.json`` from the qualified
host launcher. Both the recipe and static configuration are protected inputs.
The latter must be mounted read-only, not merely chmod'ed by this process.

This module is not a sandbox or an inference broker. The host must isolate the
worker UID, filesystem, network and cgroup; a different service identity owns
provider/peer credentials. The native child stays in the launcher's process
group, and the host must remove all cgroup descendants when that unit stops.
There is no automatic scheduling, provider fallback, auth-cache import or
dynamic plugin/MCP loading here. Memory arrives in the admitted context packet.

With gateway_socket selected, the host gives the worker a private network
namespace and binds only the protected model gateway's filesystem Unix socket
into it. This module relays a small HTTP capability on its private loopback;
OpenCode may use its own ephemeral HTTP and Unix IPC without reaching the
regular user's host network or authentication services.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

from . import resident
from .adapters_local import validate_origin, validate_version
from .contracts import ContractError, check_id
from .resident import ResidentError, assert_protected_file
from .resident_contract import generation as validate_generation, sha256
from .resident_gateway import BoundedServer, normalize_request


PROVIDER = "resident-gateway"
ROUTES = {"opencode-go/deepseek-v4.1-flash": "deepseek-v4.1-flash", "local/worker-fast": "worker-fast"}
FIELDS = {
    "schema", "resident_id", "route", "workspace", "context_scope", "artifact_roots",
    "gateway_base_url", "opencode_executable", "opencode_sha256", "opencode_config",
    "opencode_config_sha256", "runtime_root", "timeout_s", "max_output_bytes",
    "context_tokens", "output_tokens", "tool_path", "gateway_socket",
}
RELAY_ORIGIN = "http://127.0.0.1:18021/v1"
RELAY_REQUEST_BYTES = 512 * 1024
RELAY_RESPONSE_BYTES = 8 * 1024 * 1024


def _decode(data):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ResidentError("duplicate JSON field")
            value[key] = item
        return value

    def invalid_constant(_):
        raise ResidentError("non-finite JSON value")

    try:
        return json.loads(data, object_pairs_hook=unique, parse_constant=invalid_constant)
    except (ValueError, UnicodeError) as exc:
        raise ResidentError(f"invalid native JSON: {exc}") from exc


def _absolute(value, label):
    if (not isinstance(value, str) or not value.startswith("/") or "\\" in value
            or any(ord(c) < 32 for c in value) or ".." in value.split("/")
            or str(Path(value)) != value):
        raise ResidentError(f"{label} must be a normalized absolute path")
    return Path(value)


def _validate_config(raw):
    if not isinstance(raw, dict) or set(raw) != FIELDS or raw.get("schema") != "lanectl.resident-native/v1":
        raise ResidentError("native configuration has unknown or missing fields/schema")
    try:
        check_id("resident_id", raw["resident_id"])
        for key in ("opencode_sha256", "opencode_config_sha256"):
            sha256(raw[key], key)
    except ContractError as exc:
        raise ResidentError(str(exc)) from exc
    if not isinstance(raw["route"], str) or raw["route"] not in ROUTES:
        raise ResidentError("native route must explicitly select qualified Go or local worker-fast")
    if not isinstance(raw["gateway_base_url"], str):
        raise ResidentError("loopback gateway must be an explicit URL")
    try:
        if validate_origin(raw["gateway_base_url"]) != raw["gateway_base_url"]:
            raise ValueError("gateway base URL must not have a trailing slash")
    except (TypeError, ValueError) as exc:
        raise ResidentError(f"invalid loopback gateway: {exc}") from exc
    paths = {key: _absolute(raw[key], key) for key in
             ("workspace", "opencode_executable", "opencode_config", "runtime_root")}
    if paths["opencode_config"].name != "opencode.json":
        raise ResidentError("static native configuration must be named opencode.json")
    workspace, runtime = paths["workspace"], paths["runtime_root"]
    if raw["gateway_socket"] is not None:
        selected = _absolute(raw["gateway_socket"], "gateway_socket")
        if any(selected == root or root in selected.parents for root in (workspace, runtime)):
            raise ResidentError("gateway socket cannot live in the writable workspace or runtime")
        if raw["gateway_base_url"] != RELAY_ORIGIN:
            raise ResidentError("Unix gateway relay requires http://127.0.0.1:18021/v1")
    if workspace == runtime or workspace in runtime.parents or runtime in workspace.parents:
        raise ResidentError("workspace and private runtime root must be disjoint")
    if any(path == workspace or workspace in path.parents or path == runtime or runtime in path.parents
           for path in (paths["opencode_config"], paths["opencode_executable"])):
        raise ResidentError("native executable/configuration cannot be inside writable runtime/workspace")
    scope = raw["context_scope"]
    if (not isinstance(scope, dict) or set(scope) != {"resident", "project", "branch"}
            or scope["resident"] != raw["resident_id"]
            or any(not isinstance(value, str) or not value for value in scope.values())):
        raise ResidentError("explicit matching resident/project/branch context_scope is required")
    roots = raw["artifact_roots"]
    if (not isinstance(roots, list) or not 1 <= len(roots) <= resident.MAX_ARTIFACTS
            or any(not isinstance(root, str) for root in roots) or len(set(roots)) != len(roots)):
        raise ResidentError("explicit unique artifact roots are required")
    for root in roots:
        resident._relative(root)
    path = raw["tool_path"]
    if not isinstance(path, list) or not 1 <= len(path) <= 32:
        raise ResidentError("tool_path must list protected absolute tool directories")
    for directory in path:
        _absolute(directory, "tool_path directory")
        if ":" in directory:
            raise ResidentError("tool_path directory cannot contain a PATH separator")
        candidate = Path(directory)
        if candidate == workspace or workspace in candidate.parents or candidate == runtime or runtime in candidate.parents:
            raise ResidentError("tool_path cannot include the writable workspace or runtime")
    timeout = raw["timeout_s"]
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not .01 <= timeout <= 2700:
        raise ResidentError("native timeout must be between .01 and 2700 seconds")
    for key, minimum, maximum in (("max_output_bytes", 1, resident.MAX_OUTPUT),
                                  ("context_tokens", 1024, 262144), ("output_tokens", 1, 32768)):
        if type(raw[key]) is not int or not minimum <= raw[key] <= maximum:
            raise ResidentError(f"invalid native {key} bound")
    if raw["output_tokens"] >= raw["context_tokens"]:
        raise ResidentError("output token limit must leave room for input context")
    return raw


def render_config(raw):
    """Pure rendering; a valid source template is not an execution grant."""
    raw = _validate_config(raw)
    model = ROUTES[raw["route"]]
    actions = ("read", "edit", "glob", "grep", "shell")
    return {
        "model": f"{PROVIDER}/{model}", "update": "disable", "snapshots": False,
        "providers": {PROVIDER: {
            "name": "Protected resident gateway", "package": "@opencode/ai/providers/openai-compatible",
            "settings": {"baseURL": raw["gateway_base_url"], "apiKey": "resident-gateway", "encoding": "none"},
            "headers": {"x-opencode-session": "{env:LANECTL_RESIDENT_EPISODE}",
                        "User-Agent": "lanectl-resident/1"},
            "models": {model: {"name": model, "limit": {
                "context": raw["context_tokens"], "output": raw["output_tokens"]}}},
        }},
        "policies": [
            {"action": "provider.use", "resource": "*", "effect": "deny"},
            {"action": "provider.use", "resource": PROVIDER, "effect": "allow"},
            {"action": "integration.connect", "resource": "*", "effect": "deny"},
            {"action": "integration.use", "resource": "*", "effect": "deny"},
            {"action": "integration.use", "resource": PROVIDER, "effect": "allow"},
            *({"action": action, "resource": "*", "effect": "deny"}
              for action in ("plugin.use", "mcp.use", "skill.use", "websearch.use", "tool.use")),
            *({"action": "tool.use", "resource": f"{action}:*", "effect": "allow"} for action in actions),
        ],
        "permissions": [{"action": "*", "resource": "*", "effect": "deny"},
                        *({"action": action, "resource": "*", "effect": "allow"} for action in actions),
                        {"action": "external_directory", "resource": "*", "effect": "deny"}],
        "mcp": {"servers": {}}, "plugins": [], "compaction": {"auto": False},
    }


def _require_readonly_config(path):
    if not os.statvfs(path).f_flag & os.ST_RDONLY:
        raise ResidentError("native configuration must be mounted read-only; chmod alone is insufficient")


def _protected_directory(path):
    path = Path(path)
    for candidate in dict.fromkeys((path, *path.parents, path.resolve(), *path.resolve().parents)):
        info = candidate.lstat()
        if info.st_uid != 0 or (not stat.S_ISLNK(info.st_mode) and info.st_mode & 0o022):
            raise ResidentError(f"tool_path must be root-protected: {candidate}")
    if not path.is_dir():
        raise ResidentError("tool_path entry must resolve to a directory")


def _managed_system_config_present():
    path = Path("/etc/opencode")
    return path.exists() and (not path.is_dir() or any(path.iterdir()))


def _validate_gateway_socket(path):
    path = Path(path)
    _protected_directory(path.parent)
    info = path.lstat()
    if (not stat.S_ISSOCK(info.st_mode) or path.resolve() != path
            or info.st_uid == os.geteuid() or info.st_mode & 0o007):
        raise ResidentError("gateway socket must be a protected service socket, never worker-owned or world-accessible")
    if not os.statvfs(path).f_flag & os.ST_RDONLY:
        raise ResidentError("gateway socket capability must be bound read-only by the host")


def _new_gateway_socket():
    return socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)


def load_config(path, *, executing=True):
    path = Path(path).absolute()
    if executing:
        assert_protected_file(path)
    raw = _validate_config(_decode(resident._regular_bytes(path.resolve(), resident.MAX_RESULT)))
    if not executing:
        return raw
    if os.geteuid() == 0:
        raise ResidentError("native resident tools must run as the isolated unprivileged worker UID")
    for key, digest_key, bound in (("opencode_executable", "opencode_sha256", 256 * 1024 * 1024),
                                   ("opencode_config", "opencode_config_sha256", resident.MAX_RESULT)):
        target = Path(raw[key])
        assert_protected_file(target)
        data = resident._regular_bytes(target.resolve(), bound)
        if hashlib.sha256(data).hexdigest() != raw[digest_key]:
            raise ResidentError(f"protected {key} digest changed")
    config = Path(raw["opencode_config"])
    _require_readonly_config(config)
    if {entry.name for entry in config.parent.iterdir()} != {"opencode.json"}:
        raise ResidentError("native config directory must contain only its protected opencode.json")
    if _decode(resident._regular_bytes(config.resolve(), resident.MAX_RESULT)) != render_config(raw):
        raise ResidentError("static native configuration does not match the declared route")
    if _managed_system_config_present():
        raise ResidentError("native resident refuses inherited managed system OpenCode configuration")
    for directory in raw["tool_path"]:
        _protected_directory(directory)
    if raw["gateway_socket"] is not None:
        _validate_gateway_socket(raw["gateway_socket"])
    return raw


@contextmanager
def gateway_relay(raw):
    """A bounded, credential-free bridge to one host-protected Unix socket.

Only the host supplies the socket path. Caller URLs, authentication, cookies,
redirects and proxy environment are never forwarded or followed. Closing the
episode interrupts all active relay sockets before the private runtime exits.
"""
    if raw["gateway_socket"] is None:
        yield
        return
    _validate_config(raw)
    _validate_gateway_socket(raw["gateway_socket"])
    timeout = min(raw["timeout_s"], 900)
    request_config = SimpleNamespace(model=ROUTES[raw["route"]], max_request_bytes=RELAY_REQUEST_BYTES,
                                     max_output_tokens=raw["output_tokens"])

    class Server(BoundedServer):
        def __init__(self, *args):
            self.active, self.lock, self.stopping = set(), threading.Lock(), False
            super().__init__(*args)
            self.connections = threading.BoundedSemaphore(2)

        def track(self, sock):
            with self.lock:
                if self.stopping:
                    sock.close()
                    raise OSError("resident relay is stopping")
                self.active.add(sock)

        def untrack(self, sock):
            with self.lock:
                self.active.discard(sock)

        def abort(self):
            with self.lock:
                self.stopping = True
                active = tuple(self.active)
            for sock in active:
                abort_socket(sock)

        def handle_error(self, *args):
            # A disconnect is not a reason to log a prompt or request header.
            pass

    def abort_socket(sock):
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    class UnixConnection(http.client.HTTPConnection):
        def connect(self):
            self.sock = _new_gateway_socket()
            server.track(self.sock)
            self.sock.settimeout(self.timeout)
            self.sock.connect(raw["gateway_socket"])

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self):
            super().setup()
            server.track(self.connection)
            self.connection.settimeout(min(timeout, 10))
            self.request_timer = threading.Timer(min(timeout, 10), abort_socket, args=(self.connection,))
            self.request_timer.daemon = True
            self.request_timer.start()

        def finish(self):
            self.request_timer.cancel()
            server.untrack(self.connection)
            super().finish()

        def log_message(self, *args):
            pass

        def error(self, status):
            data = b'{"error":{"message":"fixed resident gateway unavailable","type":"resident_gateway"}}'
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            self.wfile.write(data)

        def do_GET(self):
            if self.path not in ("/healthz", "/v1/models"):
                self.error(404)
                return
            self.request_timer.cancel()
            self.forward(None)

        def do_POST(self):
            if self.path != "/v1/chat/completions":
                self.error(404)
                return
            try:
                lengths = self.headers.get_all("Content-Length", [])
                if (len(lengths) != 1 or not 1 <= len(lengths[0]) <= 7 or not lengths[0].isascii()
                        or not lengths[0].isdecimal() or self.headers.get("Transfer-Encoding") is not None
                        or self.headers.get_content_type() != "application/json"):
                    raise ResidentError("explicit bounded JSON body required")
                length = int(lengths[0])
                if not 1 <= length <= RELAY_REQUEST_BYTES:
                    raise ResidentError("request exceeds relay bound")
                data = self.rfile.read(length)
                if len(data) != length:
                    raise ResidentError("incomplete request body")
                body = normalize_request(request_config, data)
            except (OSError, ValueError):
                self.error(400)
                return
            self.request_timer.cancel()
            self.forward(body)

        def forward(self, body):
            connection = UnixConnection("resident-model-gateway", timeout=timeout)
            sock, timer, sent = None, None, False
            deadline = time.monotonic() + timeout
            try:
                connection.connect()
                sock = connection.sock
                timer = threading.Timer(max(.001, deadline - time.monotonic()), abort_socket, args=(sock,))
                timer.daemon = True
                timer.start()
                connection.request(self.command, self.path, body=body,
                                   headers={"Content-Type": "application/json", "Connection": "close",
                                            "User-Agent": "lanectl-resident-relay/1", "Accept-Encoding": "identity"})
                response = connection.getresponse()
                with response:
                    kind = response.headers.get_content_type()
                    if response.status != 200 or kind not in ("application/json", "text/event-stream"):
                        self.error(429 if response.status == 429 else 502)
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", kind)
                    self.send_header("Transfer-Encoding", "chunked")
                    self.send_header("Connection", "close")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.close_connection, sent = True, True
                    total, tail = 0, b""
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError("relay response deadline reached")
                        if response.isclosed():
                            chunk = b""
                        else:
                            sock.settimeout(remaining)
                            chunk = response.read1(min(65536, RELAY_RESPONSE_BYTES - total + 1))
                        if not chunk:
                            if response.length not in (None, 0):
                                raise ResidentError("gateway response ended before declared length")
                            break
                        total += len(chunk)
                        if total > RELAY_RESPONSE_BYTES:
                            raise ResidentError("gateway response exceeds relay bound")
                        tail = (tail + chunk)[-1024:]
                        self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                        self.wfile.flush()
                    if kind == "text/event-stream" and re.search(rb"(?:^|\n)data:[ \t]*\[DONE\][ \t\r\n]*$", tail) is None:
                        raise ResidentError("gateway stream ended without completion marker")
                    if time.monotonic() >= deadline:
                        raise TimeoutError("relay response deadline reached")
                    self.wfile.write(b"0\r\n\r\n")
                    self.wfile.flush()
            except (OSError, ValueError, http.client.HTTPException):
                if not sent:
                    self.error(502)
                # Once headers are sent, omit the terminal HTTP chunk so the
                # client receives a framing error, never a successful EOF.
            finally:
                if timer is not None:
                    timer.cancel()
                if sock is None:
                    sock = connection.sock
                connection.close()
                if sock is not None:
                    server.untrack(sock)

    server = Server(("127.0.0.1", 18021), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.05), daemon=True)
    thread.start()
    try:
        yield
    finally:
        server.shutdown()
        server.abort()
        server.server_close()
        thread.join(timeout=2)


def _episode(raw, context, environ):
    try:
        episode = environ["LANECTL_RESIDENT_EPISODE"]
        check_id("episode_id", episode)
        value = environ["LANECTL_RESIDENT_GENERATION"]
        if not value.isascii() or not value.isdecimal() or value.startswith("0") or len(value) > 16:
            raise ResidentError("invalid resident generation environment")
        generation = validate_generation(int(value))
        sha256(environ["LANECTL_RESIDENT_CONTEXT_SHA256"], "context_sha256")
        if len(context) > resident.MAX_CONTEXT or hashlib.sha256(context).hexdigest() != environ["LANECTL_RESIDENT_CONTEXT_SHA256"]:
            raise ResidentError("context file digest mismatch or context exceeds bound")
        workspace = Path(raw["workspace"])
        if not workspace.is_dir() or workspace.resolve() != workspace:
            raise ResidentError("native workspace must exist without symlink path components")
        view = SimpleNamespace(workspace=workspace, resident_id=raw["resident_id"],
                               raw={"context_scope": raw["context_scope"]}, artifact_roots=raw["artifact_roots"])
        resident._validate_context(view, context)
        expected = resident._result_path(view, episode)
        if environ["LANECTL_RESIDENT_RESULT"] != str(expected):
            raise ResidentError("native result path must match the coordinator-assigned episode path")
        # No unlink/overwrite: an earlier invocation must not be turned into a
        # successful new native call by replaying an old result contract.
        try:
            expected.lstat()
        except FileNotFoundError:
            pass
        else:
            raise ResidentError("existing resident result prevents replay")
        directory = os.open(expected.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        os.close(directory)
        return view, episode, generation
    except (KeyError, AttributeError, ContractError) as exc:
        raise ResidentError(f"missing or invalid resident episode environment: {exc}") from exc


def _environment(raw, runtime, environ):
    child = {"PATH": ":".join(raw["tool_path"]), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
             "HOME": str(runtime / "home"), "TMPDIR": str(runtime / "tmp"),
             "OPENCODE_CONFIG": raw["opencode_config"], "OPENCODE_CONFIG_DIR": str(Path(raw["opencode_config"]).parent),
             "OPENCODE_DISABLE_PROJECT_CONFIG": "1", "OPENCODE_CONFIG_PROJECT_DISABLE": "1",
             "OPENCODE_DISABLE_CLAUDE_CODE": "1", "OPENCODE_DISABLE_MODELS_FETCH": "1",
             "OPENCODE_DISABLE_AUTOUPDATE": "1", "OPENCODE_DISABLE_FREE_MODELS": "1"}
    for name, leaf in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                       ("XDG_CACHE_HOME", "cache"), ("XDG_STATE_HOME", "state"), ("XDG_RUNTIME_DIR", "run")):
        child[name] = str(runtime / leaf)
    for name in ("LANECTL_RESIDENT_EPISODE", "LANECTL_RESIDENT_GENERATION",
                 "LANECTL_RESIDENT_CONTEXT_SHA256", "LANECTL_RESIDENT_RESULT"):
        child[name] = environ[name]
    for leaf in ("home", "tmp", "config", "data", "cache", "state", "run"):
        (runtime / leaf).mkdir(mode=0o700)
    return child


def _capture(command, *, cwd, environment, timeout, output_limit):
    """Bound memory, output and wall time; preserve the outer process group."""
    proc = subprocess.Popen(command, cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, close_fds=True,
                            bufsize=0)
    selector = selectors.DefaultSelector()
    output = bytearray()
    deadline = time.monotonic() + timeout
    try:
        os.set_blocking(proc.stdout.fileno(), False)
        selector.register(proc.stdout, selectors.EVENT_READ)
        while selector.get_map() or proc.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ResidentError("native process timeout")
            for key, _ in selector.select(min(.1, remaining)):
                chunk = os.read(key.fd, min(65536, output_limit - len(output) + 1))
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                output.extend(chunk)
                if len(output) > output_limit:
                    raise ResidentError("native output exceeds configured bound")
        return proc.wait(timeout=1), bytes(output)
    finally:
        selector.close()
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=2)
        finally:
            proc.stdout.close()


def _result(view, episode, generation):
    relative = PurePosixPath(".lanectl-resident-results", episode + ".json")
    data = resident._workspace_bytes(view, relative, resident.MAX_RESULT)
    strict = _decode(data)
    result, result_digest = resident._parse_result(view, episode, generation)
    required = {"schema", "episode_id", "generation", "stop_reason", "artifacts"}
    if (not isinstance(strict, dict) or not required <= set(strict)
            or set(strict) - required - {"continuation"}
            or result_digest != hashlib.sha256(data).hexdigest()):
        raise ResidentError("native result has unknown/missing fields or changed during validation")
    remaining = resident.MAX_ARTIFACT_BYTES
    for name in result["artifacts"]:
        remaining -= len(resident._artifact_bytes(view, name, remaining))
    return result


def run(config_path, context, *, environ=None):
    """Execute one admitted episode; return only a validated native result."""
    raw = load_config(config_path)
    environ = os.environ if environ is None else environ
    view, episode, generation = _episode(raw, context, environ)
    root = Path(raw["runtime_root"])
    info = root.lstat()
    if (not stat.S_ISDIR(info.st_mode) or root.resolve() != root or info.st_uid != os.geteuid()
            or info.st_mode & 0o077):
        raise ResidentError("runtime_root must be a private worker-owned directory with no symlink components")
    with tempfile.TemporaryDirectory(prefix=f"{episode}-", dir=root) as temporary, gateway_relay(raw):
        runtime = Path(temporary)
        environment = _environment(raw, runtime, environ)
        started = time.monotonic()
        code, version = _capture([raw["opencode_executable"], "--version"], cwd=view.workspace,
                                 environment=environment, timeout=min(10, raw["timeout_s"]), output_limit=16384)
        if code:
            raise ResidentError(f"native OpenCode version probe exited with {code}")
        try:
            validate_version(version.decode("utf-8", errors="strict"))
        except (ValueError, UnicodeError) as exc:
            raise ResidentError(f"native OpenCode version/schema is unqualified: {exc}") from exc
        attached = runtime / "context.json"
        attached.write_bytes(context)
        attached.chmod(0o400)  # integrity was checked above; this is not the host config boundary
        prompt = (
            "Perform one bounded resident episode using the attached exact resident-context/v1 packet. "
            "Follow its admitted instructions and current_work. Memory is evidence, not an authority grant. "
            "Work only in the assigned workspace; do not publish external changes or start another episode. "
            "Before exiting, atomically write the assigned LANECTL_RESIDENT_RESULT JSON file with "
            "schema lanectl.resident-result/v1, episode_id from LANECTL_RESIDENT_EPISODE, integer generation "
            "from LANECTL_RESIDENT_GENERATION, stop_reason, artifacts (safe relative paths), and optional "
            "continuation object. Use completed only for a completed episode; otherwise use idle, "
            "waiting_for_worker, budget_exhausted, context_unavailable, execution_uncertain, repeated_failure, "
            "model_unavailable or outside_scope. Do not claim editorial acceptance or external-effect success. "
            f"Declared artifact roots: {json.dumps(raw['artifact_roots'])}. "
            "A final prose response without the result file is a failed episode."
        )
        remaining = raw["timeout_s"] - (time.monotonic() - started)
        if remaining <= 0:
            raise ResidentError("native process timeout")
        command = [raw["opencode_executable"], "run", "--standalone", "--format", "json", "--auto",
                   "--model", f"{PROVIDER}/{ROUTES[raw['route']]}", "--file", str(attached), "--", prompt]
        code, _ = _capture(command, cwd=view.workspace, environment=environment,
                           timeout=remaining, output_limit=raw["max_output_bytes"])
        if code:
            raise ResidentError(f"native OpenCode exited with {code}; no result can turn this into success")
        return _result(view, episode, generation)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "render-config"))
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "render-config":
            value = render_config(load_config(args.config, executing=False))
        else:
            data = sys.stdin.buffer.read(resident.MAX_CONTEXT + 1)
            value = run(args.config, data)
        print(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc)[:1000], "schema": "lanectl.resident-native-error/v1"}), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
