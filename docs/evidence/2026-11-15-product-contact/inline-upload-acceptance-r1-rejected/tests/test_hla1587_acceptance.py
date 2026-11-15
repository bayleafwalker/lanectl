"""HLA1587 independent acceptance draft; first-party Terra authorship."""

import base64
import email.parser
import email.policy
import hashlib
import http.server
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
import zlib
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest

ROOT = Path.cwd()
TRACE_DIR = None
A = "bank_partner_transactions"
B = "bank_partner_savings"
DISABLED = "bank_partner_disabled"
MARKER = "SECRET_VALUE https://sensitive.invalid/trace STACKTRACE"
CSV = b"booking_date,account_number,payee,amount_eur,memo\n2026-01-02,CHK-001,Electric Utility,-84.15,Monthly bill\n2026-01-03,CHK-001,Employer,2450.00,Salary\n"
INVALID = b"booking_date,account_number,payee\n2026-01-01,CHK-001,Shop\n"
JSON_BYTES = json.dumps(
    [
        {"booking_date": "2026-02-01", "account_number": "CHK-002", "payee": "JSON Utility", "amount_eur": "-20", "memo": "Bill", "entity_id": "sensor.example", "state": "on"},
    ],
    sort_keys=True,
).encode()
XLSX_ZLIB_BASE64 = "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"
XLSX = zlib.decompress(base64.b64decode(XLSX_ZLIB_BASE64))

SEED = zlib.decompress(base64.b64decode('eNq1Vk1v2zgQvedXCDpJgNfdAu2lgA6u424NJNmF7R4WRUHQ5KgiQpEqSbn1v98hadmRLGWbAvXF0gzffPHNjETdaOMSbW9Ko+ukoa6SYp+IKP4HXzsFe6Rfwc4b0YAUCp+YPZADlYJTJ7TqIEst21rtjg0MgNZpgw9zofDNIwjTqhRfO+C6ky+DeAONtgIxx/+3Qx2V+mwou0nwF+O4p02DB5cGqINZX7hpJYpuEWzBRU10PQsGzgrlDGUuqjpDW90aBgvrD/REHwzYCqtje+eDwXhge7QO6k6e3/h0ICmm08/8JWTazkEdhNHqc/rx7/vV3eI9WTws7v7drZdbcrvYLcjtepN+yZNXSRoLO+f79GR/zoI/YkMIxIYYsuuAst4BIniR7ql6JA01ToEh8MNXOJ0litZQpO9RhxwJumTV6U42HFKgSEsh4Q9udIMKrKOy/lAURycewCrgeBmk1hwhNVUtlWk+iJ3H+/CsCReSPXNB2fBwSKXSrYVKS04oY7pVjoSIUI1lt+TwGmPpgDHB5xF4/ADG4mPxepZQKfV3rBCeQLeeTbb4QKVFanSv2QjZsnSv9SOgB1+7S/fM8U5X+Sg/s7SLRvA+ZrvbrB/+mkIFDBh/mceQ4EvAtPboQYir5fp+cTfprzUGFDu+xA0Hy4xofH3HYLPEwLdWGOCxtnk+pEmsNaljj2cjYyDrH5lieeTDzzbELxPuCYMM9gCS5GpI9SlyiigmUQSVzwIDgDQfGXEDtgzgnU619R7MhIEx4gzsNPQIk/476gx9BzmBdtLvhUAcStpK5xdOi425+rSZwPQJNPBYQ63TwJlSm0RwUE6UAkwcaLMEFN1L4IlQyeesf9ODxu/Pvl1fuTMtYHQDC5YeMMpr8PYsH8dxYUNUV8DbiyI2w5d3YdGMjXzqV1V2tbayp2rP2WFNiliY394GL+nJgMYLrMOHBzl9GURMK6QTampcxzTjZjqFmp5vvTj95+NLs+w2++m7JXtm4V+V9VkuUYYjDZe9T+bpCryUFR+AOZwApR9/viWwezipNAulwxniC4BzAD0ZLaUvYQNGaM8N3vrleSS6ROvKVcWDVvDE5neE4ebCI7Z4O0sueVpJo/TNn8gAUD7Eg8ARwCQm5pe4oooJ3NV+LNdoBnNjFVUKpK+vrfaaGp6eh7YlVYupkZh6Eeie/weIw+AH')).decode()


def _port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _require_success(returncode, label):
    if returncode != 0:
        raise RuntimeError(f"{label} failed with exit {returncode}")


def _require_hash(data, expected):
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise RuntimeError(f"fixture hash mismatch: {actual}")


def _assert_group_gone(pid):
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        _trace("lifecycle", {"event": "group_absent", "pid": pid})
        return
    _trace("lifecycle", {"event": "group_alive", "pid": pid})
    raise RuntimeError(f"owned process group still exists: {pid}")


def _stop_group(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)
    _assert_group_gone(process.pid)


def _environment(data, port):
    allowed = ("PATH", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR", "LD_LIBRARY_PATH")
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    data.mkdir(parents=True, exist_ok=True)
    scratch = data / "tmp"
    scratch.mkdir(exist_ok=True)
    docker_config = data / "docker-config"
    docker_config.mkdir(exist_ok=True)
    env.update(
        DOCKER_CONFIG=str(docker_config),
        DOCKER_HOST="unix:///var/run/docker.sock",
        TMPDIR=str(scratch),
        XDG_CONFIG_HOME=str(data / "xdg-config"),
        XDG_CACHE_HOME=str(data / "xdg-cache"),
        npm_config_cache=str(data / "npm-cache"),
        npm_config_userconfig=str(data / "npmrc-user"),
        npm_config_globalconfig=str(data / "npmrc-global"),
        NEXT_TELEMETRY_DISABLED="1",
    )
    env.update(
        PYTHONDONTWRITEBYTECODE="1",
        HOMELAB_ANALYTICS_DATA_DIR=str(data),
        HOMELAB_ANALYTICS_IDENTITY_MODE="local",
        HOMELAB_ANALYTICS_SESSION_SECRET="local-test-session-secret-0123456789",
        HOMELAB_ANALYTICS_API_HOST="127.0.0.1",
        HOMELAB_ANALYTICS_API_PORT=str(port),
    )
    return env


def _trace(kind, record):
    if TRACE_DIR is None:
        return
    case = os.environ.get("PYTEST_CURRENT_TEST", "fixture")
    case_id = hashlib.sha256(case.encode()).hexdigest()[:16]
    with (TRACE_DIR / (kind + "-" + case_id + ".jsonl")).open("a") as stream:
        stream.write(json.dumps({"case": case, **record}, default=str) + "\n")


def _trace_response(response):
    response.read()
    _trace("api", {"method": response.request.method, "url": str(response.request.url), "status": response.status_code, "body": response.text})


def _login(base, role):
    client = httpx.Client(base_url=base, timeout=30, event_hooks={"response": [_trace_response]})
    response = client.post("/auth/login", json={"username": "acceptance-" + role, "password": "local-test-password-123"})
    assert response.status_code == 200, response.text
    client.headers["x-csrf-token"] = client.cookies["homelab_analytics_csrf"]
    return client


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    global TRACE_DIR
    data = tmp_path_factory.mktemp("hla1587-api")
    TRACE_DIR = data
    port = _port()
    env = _environment(data, port)
    for command in ([sys.executable, "-c", SEED], [sys.executable, "-m", "apps.worker.main", "create-local-admin-user", "acceptance-admin", "local-test-password-123"]):
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr
    log = (data / "api.log").open("wb")
    process = subprocess.Popen([sys.executable, "-m", "apps.api.main"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    _trace("lifecycle", {"event": "start_api", "pid": process.pid, "pgid": process.pid})
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            assert process.poll() is None, (data / "api.log").read_text()
            try:
                response = httpx.get(base + "/health", timeout=1)
                if response.status_code == 200:
                    break
            except httpx.TransportError:
                time.sleep(0.2)
        else:
            pytest.fail("API bootstrap unavailable")
        admin = _login(base, "admin")
        for role in ("operator", "reader"):
            response = admin.post("/auth/users", json={"username": "acceptance-" + role, "password": "local-test-password-123", "role": role})
            assert response.status_code == 201, response.text
        yield admin, base
    finally:
        try:
            _stop_group(process)
        finally:
            log.close()


def _multipart(client, path, asset, filename, content):
    data = {"source_asset_id": asset}
    if path.endswith("dry-run"):
        data["upload_path"] = "/upload/configured-csv"
    else:
        data["source_name"] = "acceptance"
    return client.post(path, data=data, files={"file": (filename, content, "application/octet-stream")})


def _rows(client):
    response = client.get("/control/source-freshness")
    assert response.status_code == 200, response.text
    return {row["source_asset_id"]: row for row in response.json()["datasets"]}


def _population(client):
    response = client.get("/runs", params={"limit": 200})
    assert response.status_code == 200
    runs = response.json()["runs"]
    assert len(runs) < 200, "run population may be truncated"
    return {run["run_id"] for run in runs}


def _detail(client, identifier, asset, mapping="bank_partner_export_v1"):
    response = client.get("/runs/" + identifier)
    assert response.status_code == 200, response.text
    run = response.json()["run"]
    assert run["context"]["source_asset_id"] == asset
    assert run["context"]["column_mapping_id"] == mapping
    assert run["context"]["source_system_id"] == "bank_partner_export"
    return run


def test_rb1_csv_pinned_identity_and_sibling(api):
    client, _ = api
    before = _rows(client)
    runs = _population(client)
    preview = _multipart(client, "/ingest/dry-run", A, "source.csv", CSV)
    assert preview.status_code == 200
    assert preview.json()["preview"]["ready"]
    assert preview.json()["preview"]["target"]["source_asset_id"] == A
    assert _population(client) == runs
    result = _multipart(client, "/ingest/configured-csv", A, "source.csv", CSV)
    assert result.status_code == 201, result.text
    identifier = result.json()["run"]["run_id"]
    _detail(client, identifier, A)
    after = _rows(client)
    assert after[A]["latest_run_id"] == identifier
    assert after[B] == before[B]


def test_rb2_xlsx(api):
    client, _ = api
    preview = _multipart(client, "/ingest/dry-run", A, "source.xlsx", XLSX)
    assert preview.status_code == 200 and preview.json()["preview"]["ready"]
    assert preview.json()["preview"]["target"]["source_asset_id"] == A
    result = _multipart(client, "/ingest/configured-csv", A, "source.xlsx", XLSX)
    assert result.status_code == 201, result.text
    _detail(client, result.json()["run"]["run_id"], A)


def test_rb3_json_detection_is_advisory(api):
    client, _ = api
    detect = client.post("/ingest/detect-source", files={"file": ("source.json", JSON_BYTES, "application/json")})
    assert detect.status_code == 200
    candidate = detect.json()["detection"]["candidate"]
    assert candidate is None or candidate.get("source_asset_id") != A
    preview = _multipart(client, "/ingest/dry-run", A, "source.json", JSON_BYTES)
    assert preview.status_code == 200 and preview.json()["preview"]["ready"], preview.text
    assert preview.json()["preview"]["target"]["source_asset_id"] == A
    result = _multipart(client, "/ingest/configured-csv", A, "source.json", JSON_BYTES)
    assert result.status_code == 201, result.text
    _detail(client, result.json()["run"]["run_id"], A)


def test_rb4_duplicate_records_sibling_run(api):
    client, _ = api
    unique = CSV.replace(b"Electric Utility", b"Duplicate control utility")
    first = _multipart(client, "/ingest/configured-csv", A, "first.csv", unique)
    assert first.status_code == 201, first.text
    before = _rows(client)[A]
    result = _multipart(client, "/ingest/configured-csv", B, "duplicate.csv", unique)
    assert result.status_code == 409, result.text
    run = result.json()["run"]
    assert run["status"] == "rejected"
    _detail(client, run["run_id"], B)
    assert _rows(client)[A] == before


def test_rb5_invalid_dry_run_and_ingest(api):
    client, _ = api
    before = _population(client)
    preview = _multipart(client, "/ingest/dry-run", A, "bad.csv", INVALID)
    assert preview.status_code == 200 and not preview.json()["preview"]["ready"]
    assert _population(client) == before
    result = _multipart(client, "/ingest/configured-csv", A, "bad.csv", INVALID)
    assert result.status_code == 400 and result.json()["run"]["status"] == "rejected"
    _detail(client, result.json()["run"]["run_id"], A)


def test_rb6_corrupt_xlsx_and_xls(api):
    client, _ = api
    for filename, content in (("corrupt.xlsx", b"not a workbook"), ("nonutf8.xls", b"\xff\xfe\x80")):
        preview = _multipart(client, "/ingest/dry-run", A, filename, content)
        assert preview.status_code == 200 and not preview.json()["preview"]["ready"], preview.text
        result = _multipart(client, "/ingest/configured-csv", A, filename, content)
        assert result.status_code == 400 and "run" not in result.json(), result.text


def test_rb7_disabled_asset(api):
    client, _ = api
    preview = _multipart(client, "/ingest/dry-run", DISABLED, "source.csv", CSV)
    assert preview.status_code == 200 and not preview.json()["preview"]["ready"], preview.text
    assert preview.json()["preview"]["issues"]
    result = _multipart(client, "/ingest/configured-csv", DISABLED, "source.csv", CSV)
    assert result.status_code == 400


def test_rb9_permissions(api):
    _, base = api
    operator = _login(base, "operator")
    reader = _login(base, "reader")
    assert operator.get("/control/source-freshness").status_code == 403
    assert _multipart(operator, "/ingest/dry-run", A, "source.csv", CSV).status_code == 200
    assert _multipart(reader, "/ingest/dry-run", A, "source.csv", CSV).status_code == 403


def test_rb10_dry_run_does_not_create_run(api):
    client, _ = api
    before = _population(client)
    result = _multipart(client, "/ingest/dry-run", A, "bad.csv", INVALID)
    assert result.status_code == 200 and not result.json()["preview"]["ready"]
    assert _population(client) == before


def test_fixture_hashes_are_stable():
    _require_hash(CSV, "bc00145b75ea05a60d10e24e43cfb362d4359b04b692575e5600bb3f5a4efda0")
    _require_hash(XLSX, "1989f413c942b7161505da8ad2e3a9d2a730972534da6d5545e011081e3d460c")


def test_rb11_shared_mapping_uses_explicit_asset(api):
    client, _ = api
    detection = client.post("/ingest/detect-source", files={"file": ("match.csv", CSV, "text/csv")})
    assert detection.status_code == 200
    candidate = detection.json()["detection"]["candidate"]
    assert candidate is not None and candidate["source_asset_id"] == A
    preview = _multipart(client, "/ingest/dry-run", B, "match.csv", CSV)
    assert preview.status_code == 200 and preview.json()["preview"]["ready"]
    assert preview.json()["preview"]["target"]["source_asset_id"] == B


def test_rb8_catalog_and_users_unchanged_by_dry_run(api):
    client, _ = api
    paths = ("/config/source-systems", "/config/dataset-contracts", "/config/column-mappings", "/config/source-assets", "/auth/users")
    before = {}
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, response.text
        before[path] = response.json()
    result = _multipart(client, "/ingest/dry-run", B, "match.csv", CSV)
    assert result.status_code == 200
    ingested = _multipart(client, "/ingest/configured-csv", B, "catalog-control.csv", CSV.replace(b"Electric Utility", b"Catalog invariant utility"))
    assert ingested.status_code == 201, ingested.text
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200 and response.json() == before[path], path


class Upstream(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self._reply()

    def do_GET(self):
        self._reply()

    def _reply(self):
        size = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(size)
        self.server.calls.append((self.command, self.path, dict(self.headers), body))
        _trace("upstream", {"method": self.command, "path": self.path, "headers": dict(self.headers), "body_base64": base64.b64encode(body).decode()})
        reply = self.server.responses.get((self.command, self.path))
        if reply is None:
            reply = self.server.responses.get((self.command, self.path.split("?", 1)[0]))
        if reply is None:
            reply = (404, {"detail": "unknown stub path"})
        status, payload = reply
        if payload is None:
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        pass


@pytest.fixture(scope="module")
def next_boundary(tmp_path_factory):
    work = tmp_path_factory.mktemp("hla1587-next")
    frontend = work / "frontend"
    shutil.copytree(ROOT / "apps/web/frontend", frontend, ignore=shutil.ignore_patterns("node_modules", ".next", ".git", "playwright-report", "test-results"), symlinks=True)
    env = _environment(work / "data", _port())
    env.update(npm_config_cache=str(work / "npm-cache"), NEXT_TELEMETRY_DISABLED="1")
    preferred = Path("/projects/dev/homelab-analytics/.tooling/node-v20.20.1-linux-x64/bin")
    if preferred.is_dir():
        env["PATH"] = str(preferred) + os.pathsep + env.get("PATH", "")
    version = subprocess.run(["node", "--version"], cwd=frontend, env=env, capture_output=True, text=True, timeout=10)
    assert version.returncode == 0 and version.stdout.startswith("v20."), version.stdout + version.stderr
    for name, command in (("npm-ci", ["npm", "ci", "--no-audit", "--no-fund"]), ("build", ["npm", "run", "build"])):
        output = work / (name + ".log")
        with output.open("wb") as stream:
            build = subprocess.Popen(command, cwd=frontend, env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            _trace("lifecycle", {"event": "start_" + name, "pid": build.pid, "pgid": build.pid, "command": command})
            try:
                exit_code = build.wait(timeout=600)
            except subprocess.TimeoutExpired:
                _stop_group(build)
                raise
        _assert_group_gone(build.pid)
        (work / (name + ".exit")).write_text(str(exit_code) + "\n")
        _require_success(exit_code, name)
    standalone = frontend / ".next/standalone"
    shutil.copytree(frontend / ".next/static", standalone / ".next/static", dirs_exist_ok=True)
    shutil.copytree(frontend / "public", standalone / "public", dirs_exist_ok=True)
    upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    upstream.frontend = frontend
    upstream.work = work
    upstream.calls = []
    upstream.responses = {}
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    port = _port()
    env.update(HOSTNAME="127.0.0.1", PORT=str(port), HOMELAB_ANALYTICS_API_BASE_URL=f"http://127.0.0.1:{upstream.server_port}", NEXT_TELEMETRY_DISABLED="1")
    log = (work / "next.log").open("wb")
    process = subprocess.Popen(["node", str(standalone / "server.js")], cwd=standalone, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    _trace("lifecycle", {"event": "start_next_stub", "pid": process.pid, "pgid": process.pid})
    base = f"http://localhost:{port}"
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            assert process.poll() is None, (work / "next.log").read_text()
            try:
                response = httpx.get(base + "/login", timeout=1)
                if response.status_code == 200:
                    break
            except httpx.TransportError:
                time.sleep(0.2)
        else:
            pytest.fail("Next bootstrap unavailable")
        yield base, upstream
    finally:
        try:
            _stop_group(process)
        finally:
            upstream.shutdown()
            thread.join(timeout=10)
            upstream.server_close()
            log.close()
        assert process.poll() is not None and not thread.is_alive(), "owned Next or upstream did not stop"


def _boundary_post(base, path, fields=None, with_file=True):
    files = {"file": ("source.csv", CSV, "text/csv")} if with_file else None
    response = httpx.post(base + path, data=fields or {}, files=files, headers={"cookie": "homelab_analytics_session=synthetic; homelab_analytics_csrf=synthetic-csrf"}, follow_redirects=False, timeout=30)
    _trace("boundary", {"path": path, "status": response.status_code, "headers": dict(response.headers), "body": response.text})
    return response


def _script(upstream, ingest_status=201, ingest_payload=None, run_status=200, run_payload=None, freshness_status=200, freshness_payload=None):
    upstream.calls.clear()
    upstream.responses = {
        ("POST", "/ingest/configured-csv"): (ingest_status, ingest_payload if ingest_payload is not None else {"run": {"run_id": "run-1", "status": "landed", "row_count": 1}, "promotion": {"skipped": True, "skip_reason": MARKER}}),
        ("POST", "/ingest/dry-run"): (200, {"preview": {"target": {"source_asset_id": A, "upload_path": "/upload/configured-csv", "confidence_label": "manual"}, "ready": True, "row_count": 1, "issues": [], "detection": {"format": "csv"}}}),
        ("GET", "/runs/run-1"): (run_status, run_payload if run_payload is not None else {"run": {"run_id": "run-1", "context": {"source_asset_id": A}}}),
        ("GET", "/control/source-freshness"): (freshness_status, freshness_payload if freshness_payload is not None else {"datasets": [{"source_asset_id": A, "latest_run_id": "run-1", "freshness_state": "current"}]}),
    }


def _json_response(response):
    assert not 300 <= response.status_code < 400, response.text
    assert "location" not in response.headers
    assert response.headers.get("content-type", "").startswith("application/json"), response.text
    for marker in ("SECRET_VALUE", "https://sensitive.invalid/trace", "STACKTRACE"):
        assert marker not in response.text
    return response.json()


def test_nb15_existing_upload_redirect_positive_control(next_boundary):
    base, upstream = next_boundary
    _script(upstream)
    response = _boundary_post(base, "/upload/configured-csv", {"source_asset_id": A})
    assert response.status_code == 303 and "/ingest-summary/run-1" in response.headers["location"]
    assert any(call[1] == "/ingest/configured-csv" for call in upstream.calls)


@pytest.mark.parametrize("route,upstream_path", [("dry-run", "/ingest/dry-run"), ("upload", "/ingest/configured-csv")])
def test_nb1_nb2_path_binding_and_forwarding(next_boundary, route, upstream_path):
    base, upstream = next_boundary
    _script(upstream)
    response = _boundary_post(base, f"/sources/{A}/{route}", {"source_asset_id": B, "source_system_id": "smuggled-system", "column_mapping_id": "smuggled-mapping", "dataset_contract_id": "smuggled-contract", "upload_path": "/upload/subscriptions", "source_name": "named"})
    _json_response(response)
    calls = [call for call in upstream.calls if call[1] == upstream_path]
    assert len(calls) == 1, calls
    _, _, headers, body = calls[0]
    normalized = {key.lower(): value for key, value in headers.items()}
    message = email.parser.BytesParser(policy=email.policy.default).parsebytes(("Content-Type: " + normalized["content-type"] + "\r\nMIME-Version: 1.0\r\n\r\n").encode() + body)
    fields = {part.get_param("name", header="content-disposition"): part.get_payload(decode=True) for part in message.iter_parts()}
    expected = {"file", "source_asset_id", "upload_path"} if route == "dry-run" else {"file", "source_asset_id", "source_name"}
    assert set(fields) == expected
    assert fields["file"] == CSV and fields["source_asset_id"] == A.encode()
    if route == "dry-run":
        assert fields["upload_path"] == b"/upload/configured-csv"
    assert "homelab_analytics_session=synthetic" in normalized.get("cookie", "")
    assert normalized.get("x-csrf-token") == "synthetic-csrf"


@pytest.mark.parametrize("state", ["current", "unconfigured"])
def test_nb3_landed_reports_observed_freshness(next_boundary, state):
    base, upstream = next_boundary
    _script(upstream, freshness_payload={"datasets": [{"source_asset_id": A, "latest_run_id": "run-1", "freshness_state": state}]})
    response = _boundary_post(base, f"/sources/{A}/upload")
    payload = _json_response(response)
    assert response.status_code == 201 and payload["outcome"] == "landed"
    assert payload["run_id"] == "run-1" and payload["freshness_state"] == state
    assert len(upstream.calls) >= 3


@pytest.mark.parametrize("case", ["wrong_context", "superseded", "missing_row", "read_500", "read_403", "read_reset"])
def test_nb4_nb5_context_and_observation(next_boundary, case):
    base, upstream = next_boundary
    _script(upstream)
    if case == "wrong_context":
        upstream.responses[("GET", "/runs/run-1")] = (200, {"run": {"run_id": "run-1", "context": {"source_asset_id": B}}})
    if case == "superseded":
        upstream.responses[("GET", "/control/source-freshness")] = (200, {"datasets": [{"source_asset_id": A, "latest_run_id": "other-run", "freshness_state": "current"}]})
    if case == "missing_row":
        upstream.responses[("GET", "/control/source-freshness")] = (200, {"datasets": []})
    if case in ("read_500", "read_403", "read_reset"):
        upstream.responses[("GET", "/runs/run-1")] = (500 if case == "read_500" else 403, None if case == "read_reset" else {"detail": MARKER})
    response = _boundary_post(base, f"/sources/{A}/upload")
    payload = _json_response(response)
    assert response.status_code == 201
    if case == "wrong_context":
        assert payload["outcome"] == "identity_mismatch"
    elif case in ("read_500", "read_403", "read_reset"):
        assert payload["outcome"] == "landed_unconfirmed"
    else:
        assert payload["outcome"] in ("landed", "landed_unconfirmed")
        assert payload["outcome"] != "identity_mismatch"


@pytest.mark.parametrize("status,body,outcome", [(400, {"run": {"run_id": "run-1", "status": "rejected", "issues": [{"code": "unknown", "message": MARKER}]}}, "rejected"), (400, {"detail": MARKER}, "outcome_unknown"), (409, {"run": {"run_id": "run-1", "status": "rejected", "issues": [{"code": "duplicate_file", "message": MARKER}]}}, "duplicate"), (401, {"detail": MARKER}, "auth_required"), (403, {"detail": MARKER}, "forbidden"), (404, {"detail": MARKER}, "unknown_source"), (422, {"detail": MARKER}, "malformed_request")])
def test_nb6_nb7_nb8_nb9_nb10_safe_errors(next_boundary, status, body, outcome):
    base, upstream = next_boundary
    _script(upstream, ingest_status=status, ingest_payload=body)
    response = _boundary_post(base, f"/sources/{A}/upload")
    payload = _json_response(response)
    assert response.status_code == status and payload["outcome"] == outcome
    assert len([call for call in upstream.calls if call[1] == "/ingest/configured-csv"]) == 1


@pytest.mark.parametrize("payload", [b"not json SECRET_VALUE https://sensitive.invalid/trace STACKTRACE", {"ok": True}])
def test_nb11_malformed_outcome_unknown(next_boundary, payload):
    base, upstream = next_boundary
    _script(upstream, ingest_status=200, ingest_payload=payload)
    result = _boundary_post(base, f"/sources/{A}/upload")
    body = _json_response(result)
    assert result.status_code == 502 and body["outcome"] == "outcome_unknown"


def test_nb12_transport_failure(next_boundary):
    base, upstream = next_boundary
    _script(upstream, ingest_status=500, ingest_payload={"error": MARKER})
    response = _boundary_post(base, f"/sources/{A}/upload")
    assert response.status_code == 502 and _json_response(response)["outcome"] == "outcome_unknown"
    upstream.calls.clear()
    upstream.responses[("POST", "/ingest/configured-csv")] = (500, None)
    response = _boundary_post(base, f"/sources/{A}/upload")
    assert response.status_code == 502 and _json_response(response)["outcome"] == "outcome_unknown"
    assert len([call for call in upstream.calls if call[1] == "/ingest/configured-csv"]) == 1


@pytest.mark.parametrize("route", ["dry-run", "upload"])
def test_nb13_missing_file_makes_no_upstream_call(next_boundary, route):
    base, upstream = next_boundary
    _script(upstream)
    response = _boundary_post(base, f"/sources/{A}/{route}", with_file=False)
    assert response.status_code == 400
    _json_response(response)
    assert upstream.calls == []


def test_nb16_dry_run_status_and_transport(next_boundary):
    base, upstream = next_boundary
    _script(upstream)
    result = _boundary_post(base, f"/sources/{A}/dry-run")
    assert result.status_code == 200 and _json_response(result)["target"]["source_asset_id"] == A
    upstream.responses[("POST", "/ingest/dry-run")] = (400, {"detail": MARKER})
    result = _boundary_post(base, f"/sources/{A}/dry-run")
    assert result.status_code == 400
    _json_response(result)
    upstream.responses[("POST", "/ingest/dry-run")] = (500, None)
    result = _boundary_post(base, f"/sources/{A}/dry-run")
    assert result.status_code == 502
    _json_response(result)


BROWSER_SCRIPT = zlib.decompress(base64.b64decode('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')).decode()


@pytest.fixture(scope="module")
def real_page(api, next_boundary):
    client, api_base = api
    _, upstream = next_boundary
    work = upstream.work
    frontend = upstream.frontend
    fixture_a = CSV.replace(b"Electric Utility", b"Page baseline A")
    fixture_b = CSV.replace(b"Electric Utility", b"Page baseline B")
    run_ids = []
    for asset, content in ((A, fixture_a), (B, fixture_b)):
        result = _multipart(client, "/ingest/configured-csv", asset, "baseline.csv", content)
        assert result.status_code == 201, result.text
        identifier = result.json()["run"]["run_id"]
        _detail(client, identifier, asset)
        run_ids.append(identifier)
    (work / "browser.cjs").write_text(BROWSER_SCRIPT)
    (work / "normal.csv").write_bytes(CSV.replace(b"Electric Utility", b"Ordinary browser upload"))
    (work / "aria.csv").write_bytes(CSV.replace(b"Electric Utility", b"Aria announcement upload"))
    (work / "inline.csv").write_bytes(CSV.replace(b"Electric Utility", b"Inline browser upload"))
    (work / "duplicate.csv").write_bytes(fixture_a)
    (work / "invalid.csv").write_bytes(INVALID)
    (work / "unique.json").write_bytes(JSON_BYTES.replace(b"JSON Utility", b"Browser JSON Utility"))
    assert XLSX[-2:] == b"\x00\x00"
    (work / "unique.xlsx").write_bytes(XLSX[:-2] + b"\x01\x00X")
    port = _port()
    env = _environment(work / "web-data", _port())
    preferred = Path("/projects/dev/homelab-analytics/.tooling/node-v20.20.1-linux-x64/bin")
    if preferred.is_dir():
        env["PATH"] = str(preferred) + os.pathsep + env.get("PATH", "")
    env.update(HOSTNAME="127.0.0.1", PORT=str(port), HOMELAB_ANALYTICS_API_BASE_URL=api_base)
    standalone = frontend / ".next/standalone"
    log = (work / "real-next.log").open("wb")
    process = subprocess.Popen(["node", str(standalone / "server.js")], cwd=standalone, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    _trace("lifecycle", {"event": "start_next_real", "pid": process.pid, "pgid": process.pid})
    try:
        base = f"http://localhost:{port}"
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            assert process.poll() is None, (work / "real-next.log").read_text()
            try:
                response = httpx.get(base + "/login", timeout=1)
                if response.status_code == 200:
                    break
            except httpx.TransportError:
                pass
            time.sleep(0.2)
        else:
            pytest.fail("real Next unavailable")
        yield base, work, run_ids, client
    finally:
        try:
            _stop_group(process)
        finally:
            log.close()


def _browser_case(real_page, case):
    base, work, run_ids, client = real_page
    before = _population(client)
    before_rows = _rows(client)
    name = "hla1587-" + uuid.uuid4().hex
    env = _environment(work / ("browser-env-" + name), _port())
    preferred = Path("/projects/dev/homelab-analytics/.tooling/node-v20.20.1-linux-x64/bin")
    if preferred.is_dir():
        env["PATH"] = str(preferred) + os.pathsep + env.get("PATH", "")
    browser_cache = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or str(Path.home() / ".cache/ms-playwright")
    env["PLAYWRIGHT_BROWSERS_PATH"] = browser_cache
    probe_command = ["node", "-e", "const p=require('./node_modules/playwright');(async()=>{const b=await p.chromium.launch({headless:true,args:['--no-sandbox']});await b.close()})().catch(e=>{console.error(e);process.exit(1)})"]
    probe = subprocess.Popen(probe_command, cwd=work / "frontend", env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    _trace("lifecycle", {"event": "start_browser_probe", "pid": probe.pid, "pgid": probe.pid})
    try:
        probe_output, _ = probe.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        _stop_group(probe)
        probe_output, _ = probe.communicate()
    _assert_group_gone(probe.pid)
    native = probe.returncode == 0
    (work / ("native-probe-" + name + ".log")).write_text("COMMAND " + repr(probe_command) + "\nEXIT " + str(probe.returncode) + "\n" + probe_output)
    env.update(WEB_BASE=base, CASE_ID=case, RUN_A=run_ids[0], RUN_B=run_ids[1])
    if native:
        env["WORK_DIR"] = str(work)
        command = ["node", str(work / "browser.cjs")]
    else:
        command = ["docker", "run", "--pull=never", "--name", name, "--label", "hla.acceptance=" + name, "--network", "host", "-v", str(work) + ":/work:ro", "-e", "WORK_DIR=/work", "-e", "WEB_BASE=" + base, "-e", "CASE_ID=" + case, "-e", "RUN_A=" + run_ids[0], "-e", "RUN_B=" + run_ids[1], "sha256:b0ab6f3cb99aa7803adbc14d9027ec1785fc6e433b97e134e0f8fe61683b6b53", "node", "/work/browser.cjs"]
    evidence = work / ("browser-" + case + "-" + name + ".log")
    try:
        process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
        _trace("lifecycle", {"event": "start_browser", "pid": process.pid, "pgid": process.pid, "container": None if native else name})
        try:
            output, _ = process.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            _stop_group(process)
            output, _ = process.communicate()
            evidence.write_text("COMMAND " + repr(command) + "\nTIMEOUT\n" + output)
            raise
        _assert_group_gone(process.pid)
        evidence.write_text("COMMAND " + repr(command) + "\nEXIT " + str(process.returncode) + "\n" + output)
        assert process.returncode == 0, evidence.read_text()
        assert "RESULT " in output, evidence.read_text()
        after = _population(client)
        if case in ("RP1", "RP2-xlsx", "RP2-json", "RP4", "RP5", "RP6", "RP10"):
            new = after - before
            assert len(new) == 1, (case, before, after)
            target = B if case == "RP4" else A
            run = _detail(client, next(iter(new)), target)
            if case == "RP4":
                assert run["status"] == "rejected"
            else:
                assert run["status"] == "landed"
            after_rows = _rows(client)
            sibling = A if target == B else B
            assert after_rows[sibling] == before_rows[sibling]
            assert after_rows[target]["latest_run_id"] == next(iter(new))
        if case in ("RP3", "RP7", "RP-nojs"):
            assert after == before, (case, before, after)
    finally:
        if not native:
            cleanup = subprocess.run(["docker", "rm", "-f", name], env=env, capture_output=True, text=True, timeout=30)
            inspect = subprocess.run(["docker", "ps", "-a", "--filter", "name=^/" + name + "$", "--format", "{{.ID}}"], env=env, capture_output=True, text=True, timeout=30)
            with evidence.open("a") as stream:
                stream.write("\nCLEANUP " + repr((cleanup.returncode, cleanup.stdout, cleanup.stderr, inspect.returncode, inspect.stdout, inspect.stderr)))
            assert inspect.returncode == 0 and not inspect.stdout.strip(), evidence.read_text()


def test_rp8_rp9_and_page_positive_controls(real_page):
    _browser_case(real_page, "positive")


@pytest.mark.parametrize("case", ["RP1", "RP2-xlsx", "RP2-json", "RP3", "RP4", "RP5", "RP6", "RP7", "RP10", "RP-nojs"])
def test_rp_inline_feature(real_page, case):
    _browser_case(real_page, case)


@pytest.mark.parametrize("state,words", [("disabled", ("disabled",)), ("source_system_disabled", ("system", "disabled")), ("unsupported", ("mapping",)), ("not_found", ("not", "found")), ("config_unavailable", ("unavailable",)), ("empty", ("unavailable",)), ("free_string", ("upload to example bank",))])
def test_nb17_availability_states(next_boundary, state, words):
    base, upstream = next_boundary
    _script(upstream)
    asset = {"source_asset_id": A, "name": "Example Bank", "source_system_id": "bank_partner_export", "dataset_contract_id": "household_account_transactions_v1", "column_mapping_id": "bank_partner_export_v1", "enabled": state != "disabled", "archived": False, "asset_type": "dataset"}
    if state == "empty":
        asset["source_asset_id"] = ""
    if state == "free_string":
        asset["asset_type"] = "custom-device"
    source = {"source_system_id": "bank_partner_export", "enabled": state != "source_system_disabled", "transport": "custom-transport"}
    mapping = {"column_mapping_id": "bank_partner_export_v1", "source_system_id": "bank_partner_export", "dataset_contract_id": "household_account_transactions_v1"}
    contract = {"dataset_contract_id": "household_account_transactions_v1"}
    upstream.responses.update({
        ("GET", "/auth/me"): (200, {"user": {"username": "stub-admin", "role": "admin"}}),
        ("GET", "/runs"): (200, {"runs": []}),
        ("GET", "/control/source-freshness"): (200, {"datasets": [{"source_asset_id": "" if state == "empty" else A, "dataset_name": "household_account_transactions", "name": "Example Bank", "freshness_state": "unconfigured", "latest_run_id": None, "status": None, "landed_at": None}]}),
        ("GET", "/config/source-assets"): (500, {"detail": "unavailable"}) if state == "config_unavailable" else (200, {"source_assets": [] if state == "not_found" else [asset]}),
        ("GET", "/config/source-systems"): (200, {"source_systems": [source]}),
        ("GET", "/config/column-mappings"): (200, {"column_mappings": [] if state == "unsupported" else [mapping]}),
        ("GET", "/config/dataset-contracts"): (200, {"dataset_contracts": [contract]}),
    })
    result = httpx.get(base + "/sources", headers={"cookie": "homelab_analytics_session=synthetic"}, timeout=30)
    assert result.status_code == 200
    row_match = re.search(r"<tr\b[^>]*>(?:(?!</tr>).)*Example Bank(?:(?!</tr>).)*</tr>", result.text, flags=re.DOTALL)
    assert row_match is not None, "source row missing"
    row_html = row_match.group().lower()
    assert all(word in row_html for word in words), row_html
    if state != "free_string":
        assert 'type="file"' not in row_html
    assert not any(call[1].startswith("/ingest/") for call in upstream.calls)
    assert any(call[1].startswith("/config/") for call in upstream.calls), "availability did not consult the catalog"


def test_nb6_known_issue_context_is_safe(next_boundary):
    base, upstream = next_boundary
    issue = {"code": "missing_required_value", "message": MARKER, "column": "amount", "row_number": 2}
    _script(upstream, ingest_status=400, ingest_payload={"run": {"run_id": "run-1", "status": "rejected", "issues": [issue]}})
    result = _boundary_post(base, f"/sources/{A}/upload")
    payload = _json_response(result)
    assert result.status_code == 400
    assert payload["issues"]
    assert payload["issues"][0]["code"] == "missing_required_value"
    assert payload["issues"][0]["column"] == "amount"
    assert payload["issues"][0]["row_number"] == 2
    assert MARKER not in json.dumps(payload)


@pytest.mark.parametrize("latest", ["old-run", "different-run"])
def test_nb7_no_receipt_never_attributes_latest_pointer(next_boundary, latest):
    base, upstream = next_boundary
    _script(upstream, ingest_status=400, ingest_payload={"error": MARKER}, freshness_payload={"datasets": [{"source_asset_id": A, "latest_run_id": latest, "freshness_state": "current"}]})
    result = _boundary_post(base, f"/sources/{A}/upload", {"expected_prior_run_id": "old-run"})
    payload = _json_response(result)
    assert result.status_code == 400 and payload["outcome"] == "outcome_unknown"
    text = json.dumps(payload).lower()
    assert "no new run" not in text
    assert "this upload created" not in text
    assert len([call for call in upstream.calls if call[1] == "/ingest/configured-csv"]) == 1


def test_identity_guard_rejects_wrong_source(api):
    client, _ = api
    result = _multipart(client, "/ingest/configured-csv", A, "guard.csv", CSV.replace(b"Electric Utility", b"Guard-only unique utility"))
    assert result.status_code == 201
    identifier = result.json()["run"]["run_id"]
    _detail(client, identifier, A)
    with pytest.raises(AssertionError) as wrong_asset:
        _detail(client, identifier, B)
    with pytest.raises(AssertionError) as wrong_mapping:
        _detail(client, identifier, A, mapping="wrong-mapping")
    _trace("guard", {"wrong_asset": str(wrong_asset.value), "wrong_mapping": str(wrong_mapping.value)})


def test_guards_fail_closed_on_wrong_hash_and_live_group(tmp_path):
    _require_hash(CSV, "bc00145b75ea05a60d10e24e43cfb362d4359b04b692575e5600bb3f5a4efda0")
    with pytest.raises(RuntimeError, match="fixture hash mismatch") as mismatch:
        _require_hash(CSV, "0" * 64)
    _trace("guard", {"hash_mismatch": str(mismatch.value)})
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
    try:
        with pytest.raises(RuntimeError, match="process group still exists"):
            _assert_group_gone(process.pid)
    finally:
        _stop_group(process)
    _assert_group_gone(process.pid)


def test_failed_npm_is_an_infrastructure_error(tmp_path):
    (tmp_path / "package.json").write_text('{"name":"unlocked-control","version":"1.0.0"}')
    env = _environment(tmp_path, _port())
    env.update(npm_config_cache=str(tmp_path / "npm-cache"), NEXT_TELEMETRY_DISABLED="1")
    preferred = Path("/projects/dev/homelab-analytics/.tooling/node-v20.20.1-linux-x64/bin")
    if preferred.is_dir():
        env["PATH"] = str(preferred) + os.pathsep + env.get("PATH", "")
    result = subprocess.run(["npm", "ci", "--offline", "--no-audit", "--no-fund"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    _trace("guard", {"npm_exit": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
    assert result.returncode != 0, result.stdout + result.stderr
    with pytest.raises(RuntimeError, match="npm control failed"):
        _require_success(result.returncode, "npm control")


def test_unavailable_api_is_not_semantic_red():
    port = _port()
    with pytest.raises(httpx.TransportError):
        httpx.get(f"http://127.0.0.1:{port}/health", timeout=1)


def test_nb16_dry_run_sanitizes_issue_context(next_boundary):
    base, upstream = next_boundary
    _script(upstream)
    upstream.responses[("POST", "/ingest/dry-run")] = (200, {"preview": {"target": {"source_asset_id": A, "upload_path": "/upload/configured-csv", "confidence_label": "manual"}, "ready": False, "row_count": 1, "issues": [{"code": "unknown", "message": MARKER, "column": "SECRET_VALUE", "row_number": "STACKTRACE"}], "detection": {"format": "csv"}}})
    result = _boundary_post(base, f"/sources/{A}/dry-run")
    payload = _json_response(result)
    assert result.status_code == 200 and not payload["ready"]
    assert payload["issues"]


def test_rb_opaque_source_identity(api):
    client, _ = api
    opaque = "bank/été%2F"
    body = {"source_asset_id": opaque, "source_system_id": "bank_partner_export", "dataset_contract_id": "household_account_transactions_v1", "column_mapping_id": "bank_partner_export_v1", "transformation_package_id": "builtin_account_transactions", "name": "Opaque bank", "asset_type": "dataset", "enabled": True}
    created = client.post("/config/source-assets", json=body)
    assert created.status_code == 201, created.text
    catalog = client.get("/config/source-assets")
    assert catalog.status_code == 200
    assert any(item["source_asset_id"] == opaque for item in catalog.json()["source_assets"])
    before = _rows(client)[B]
    content = CSV.replace(b"Electric Utility", b"Opaque identity utility")
    preview = _multipart(client, "/ingest/dry-run", opaque, "opaque.csv", content)
    assert preview.status_code == 200 and preview.json()["preview"]["ready"], preview.text
    assert preview.json()["preview"]["target"]["source_asset_id"] == opaque
    result = _multipart(client, "/ingest/configured-csv", opaque, "opaque.csv", content)
    assert result.status_code == 201, result.text
    identifier = result.json()["run"]["run_id"]
    _detail(client, identifier, opaque)
    rows = _rows(client)
    assert rows[opaque]["latest_run_id"] == identifier and rows[B] == before


@pytest.mark.parametrize("route", ["dry-run", "upload"])
def test_nb_opaque_source_identity(next_boundary, route):
    base, upstream = next_boundary
    opaque = "bank/été%2F"
    _script(upstream, run_payload={"run": {"run_id": "run-1", "context": {"source_asset_id": opaque}}}, freshness_payload={"datasets": [{"source_asset_id": opaque, "latest_run_id": "run-1", "freshness_state": "unconfigured"}]})
    upstream.responses[("POST", "/ingest/dry-run")] = (200, {"preview": {"target": {"source_asset_id": opaque, "upload_path": "/upload/configured-csv", "confidence_label": "manual"}, "ready": True, "row_count": 1, "issues": [], "detection": {"format": "csv"}}})
    response = _boundary_post(base, "/sources/" + quote(opaque, safe="") + "/" + route, {"source_asset_id": A})
    payload = _json_response(response)
    if route == "dry-run":
        assert payload["target"]["source_asset_id"] == opaque
    path = "/ingest/dry-run" if route == "dry-run" else "/ingest/configured-csv"
    calls = [call for call in upstream.calls if call[1] == path]
    assert len(calls) == 1
    headers = {key.lower(): value for key, value in calls[0][2].items()}
    body = calls[0][3]
    message = email.parser.BytesParser(policy=email.policy.default).parsebytes(("Content-Type: " + headers["content-type"] + "\r\nMIME-Version: 1.0\r\n\r\n").encode() + body)
    fields = {part.get_param("name", header="content-disposition"): part.get_payload(decode=True) for part in message.iter_parts()}
    assert fields["source_asset_id"].decode() == opaque


def test_self_cli_rejects_missing_population(tmp_path):
    env = _environment(tmp_path, _port())
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--collect-only", "-k", "no_such_hla1587_case", "--basetemp=" + str(tmp_path / "nested")], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    _trace("guard", {"command": "self-cli --collect-only -k no_such_hla1587_case", "exit": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
    assert result.returncode != 0, "self-CLI silently accepted an empty population"
    assert "population mismatch" in result.stdout + result.stderr


EXPECTED_CASES = tuple(zlib.decompress(base64.b64decode('eNqVVslyGzkMvc9X+Ad6tEt2bi6XT8lhyvHMRZVCsZtoiQ6bZAhSy3z9gOzFSzxaDqxqCe+BAIgtIAXwDpTRyiDUKEL0uH76qzD2hX78EZLclJMViJ1QWpRKq3AECoIl69oj8rdXZlPsrZe07Bi+BOvEr8hSG32FoCSawMxe4f+I19IfCx/Nj3O46LQV8px92LhwbC1bDJZNoKIdOGUMykEhCCOBVMlR2PTAKRw0HfpfM3gha0BiwCoo/lIEQu4UWX/sMXOQbJiq+HLwWKV7e6XAXvWwBYd7J7SSwO4mQb6dQSzuMUtguo8uZCMygD966QqkIlFq9kAQ4cC6A4e+UURs4ACejId7pEUCYwNUHrORvVG1OqSHh62gLUOET++aLhiUTIC2/LeERjiXHIrEQDwkf1V4b8YtcAiEtptsNwM9QTTVVrCLEspjb8/wfAtWpChktfllOXxScQgDOEsqqB1yPEzwVg8cPlNwImyhVEYmarqstn4vfPrZ51IxaiM7+phb5zW0tgwK2IJabThMsuAUGvTMQDMPk83O+kBgS/Z4x39wfdDWING6it5zpl3F4YgNFw7EOZ9FjgUeQra3ZYqUk+u9t+xFJ72QQ5FzhlBefEnOr5TRdn8hg5NNwmI8vgY+H8+ugXPU8NXjJZ8Vn1s+d+mpx0CiRkDvraf1fDwuSiuP48LjCyfZG9cvZE4KG0NlG+S8/mns3lyu4C4rmBZDq7icOsnUWSEi56zHX1H5a0yfZfq84AwvleTOdzl1nqmLovO268cX86fTzF8WjdB8e5MTn/s6vT4ZN5hX4Yfgrrll3aT2e/P98eHp8Rn+uf/29+PNNgRHX0YjQtP2iD+7vjoKXlR48/35/uHr89P9w+NltzhxTPU+eUVPgTUZSiUKNc8XLsVBNoO+EGqlkdX+zL2VGxhPRBQN90CtfxtoF9I+zrfl0MLTaIuUi2Cwreu77pbPXRY5scHfWmc/ET4Z973Pn8mmRRpBJwHpbU4AZidk8xOyxQnZ8oRsdUI2GZ/bGvrR2i4OZ+HdakJHCtjAe/LkHDkabr/pCXvG9BwjTe/aRtPhZ+fw7QzhHO+EGlvi/E3xtjXNaRlx6LK83qQS7kGrlKM8kFHxSmJwhx5E4M2vjAzgYZZhziom+7XV8l3SX0WWqq4xDcs3KoY1bRN5NEPbtQnacdc+QAvMcsq1CpW2lKrcdLi02+Ti0KkmNt5G1y0/jGagcU1e6jgSpvaCyzFWeSnKXayFvgkjCKcSPj0IYSPYwCqtLZ/VrDBciP+yr+9i3CIJdc22qsGrvj8466LOI+4/m1uLNg==')).decode().splitlines())


def _validate_population(names):
    if len(names) != len(set(names)) or set(names) != set(EXPECTED_CASES):
        raise RuntimeError("population mismatch: expected " + repr(EXPECTED_CASES) + "; got " + repr(names))


class PopulationAudit:
    def __init__(self):
        self.completed = []

    def pytest_collection_finish(self, session):
        names = [item.name for item in session.items]
        try:
            _validate_population(names)
        except RuntimeError as exc:
            pytest.exit(str(exc), returncode=2)

    def pytest_runtest_logreport(self, report):
        if report.when == "call" and report.passed:
            self.completed.append(report.nodeid.rsplit("::", 1)[-1])

    def pytest_sessionfinish(self, session, exitstatus):
        if exitstatus == 0:
            try:
                _validate_population(self.completed)
            except RuntimeError as exc:
                print(str(exc), file=sys.stderr)
                session.exitstatus = 2


if __name__ == "__main__":
    raise SystemExit(pytest.main(["-q", "-p", "no:cacheprovider", *sys.argv[1:], __file__], plugins=[PopulationAudit()]))
