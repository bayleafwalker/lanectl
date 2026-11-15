"""HLA1587 independent acceptance draft; first-party Terra authorship."""

import base64
import ctypes
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
XLSX_ZLIB_BASE64 = "eNp9VQs4lFkYnjEGIWyRWZlF5c7MkEiEXGIyLjGFIddGakamTCqS+65L4xJKlEuhXMety4pa91DDzJJLzETIZQyGaCR2bLuPZbc95/nO+c7//O/3nPM+532PrSWIVxwAAAhwQ84Fd3OtPo6bzXFDiBtuF7F4fzhsfSR16InUI8R4O4scg0Lx2dlGMarpVUqSCIpC+YpTe4Dps8Mw0P1s6TfjyN8HWws8D450N6oFzBizPNTlXX+odG0tGiDk2mbcSXbIa65yR/cXRs0OPJFEmYNOX9Zq+hy7kPBqHq816OiXacwBhqgb3VBRRwf2Qg10+/grfVUEPdMCLRqIPGEVDQm/sLfbbtqz2aVLX3q52TIQANjJnZ1N/M4TseeJbuirBKz/KdgVX3xJUq01SEO4xU2+DXMABoXYkoWwUSI1oa2cQOqoZblz/FPF7Z1AicbfTsuvJWTJ+2UyNMvTIxIGJo7vYwDLoMqyGSnKJ7EW8tldZ3SNjuoNhbnXYgbDrY4rtdlRoIHP+6ih5vBJj1IG045JlOvADIZAOoqtvSh0p5TCBuVFhlK7TXhB69gQFeuKjjhJkKDmymxzq3u4M3U40C5IjR2d0+++OJve1rg3CVF1wes6+XkFQYrvTIHNIuRcIwEWGawqRHdZlgxxHJHPm8ji+KaHwlx3hQawp/U2EzFShmMhuCQo8QAAotwvV/Dwy34XcZ5+frh1EkiJVOsGhLBZSF4bf+f5cCRqyjUtFCkgZhLUgbn8+FZj6ofzZWRFpDJqOEqxpedta63r3WhRvfsmix6keX/YCVXam/kBB3XHafIjkKT39vLuHRj6xy4tx7rYQnp48jWMeOXdOp8jF180UYrCFmVuzUCI086Acm8jJ5K1uuSDSgcKuz2et/CzPfpBhdlBDiOq19t84ZlJBNupcEE7WzNORD0zB3YiR5NBm0iCdIyYZlg1nUYVKDS4C6k5fk3SoY49p3Nyo+m1Ta/z0iWAvbJByN0x5IjWvZGjOVNRLKrA7DEhfcQnaHVwfSSEYxZPjC33tnZWOnH/qFBO8VRdPC/F7GCmF2S2elUhPk1KimhryB+fECFWKChJkk/K79FJfuf+QmcM5gNnxRC/fsDpT7KFNpNb1mk9l8jNFrkh9Y3cb+L4J8V/CeWwIJdn8PsiCFT22CGiEjIf5mQJc5fWFYkJKUOn01/kW9qPdyJrlt6DHuv0V6lplDnvKBr0C9Mj7JkIf9Wc1OPSZJqjpu1NzmvU96J5d+8fKijtSEvgW5imoj/spxp6VgVoEEljLOVXohAZDTIzmrfr0TyKBmS9e+h9LStfRfORx6SsqD1I8Muul3Sm2+ZzPLRn3xzmXpIDYAAAsnFJ/H2wWKI//M9JY/0oqSm+Nu8QYi0vY1OXSgYjNSNvWuA8PPsTxSR2zyRmuOwWMuT9WFHMuB6glJPMtKppGxxdXZpNvsZxZ/r3AGQ5Jbms2NwjeLjydCGf+MxYPnh6lXnjhPQ93FIVTn02UFwZad9MKRg2VsQaNLPwdzJ+yusknEH2qDZNe4BpwmYVFnSeJU/Ge0g2ls4+jAfIYBQJsHuTXcZhrEhqY32phQEcRq48ruG9IoYgKmrPteNJVxcpPdUWaVnb9qHHLQlLHDAukeZwMblGOk5hxqqW3XVddQ07wCA9HYUWk1aUz+FjR/bIHWBegc/RhXUIA2c5BsMS5q5jb4Ubl7HtNeyf/SZ2RC0mavuccnlm7bg8FEU37JaWeziuMHcBA71UlBbvkDpxwGDC1beOL2UqrWKUX+BxdewTOy/FcRPfUi8VcNvKPRtoSgzqUBJyL9juVmZHr2czTex22rnged/m3j28+xScfoyAYug3W2YyzGm4ORo/sEnwNYwyFocVsEZdwGlps42eGLeFGLUpWPStyWLlLPpa5LAyYaYEhJwt9WzHLTzFMRqNqhiiDcaL7Q1kD6zo/joaACea72O6yGuvjfyUFxycRRZJD9A3dI7w6fLRZhWHfdrGWqOUHNRdNUDdrlgB2VoCecRB3/f+v1soELD5JdgK3GrAG8Cq/7bjrQW2GtdGgVrgv2xsK3irMDfAUqD/k+nWOluFsVFnGPR9mdhagvnW/wJzuxkXvQxeX/0BH3UOog=="
XLSX = zlib.decompress(base64.b64decode(XLSX_ZLIB_BASE64))

SEED = r'''
import os
from pathlib import Path
from packages.pipelines.csv_validation import ColumnType
from packages.storage.ingestion_config import IngestionConfigRepository
from packages.storage.ingestion_catalog import (
    ColumnMappingCreate, ColumnMappingRule, DatasetColumnConfig,
    DatasetContractConfigCreate, SourceAssetCreate, SourceFreshnessConfigCreate,
    SourceSystemCreate,
)
store = IngestionConfigRepository(Path(os.environ["HOMELAB_ANALYTICS_DATA_DIR"]) / "config.db")
store.create_source_system(SourceSystemCreate(source_system_id="bank_partner_export", name="Bank Partner Export", source_type="file-drop", transport="filesystem", schedule_mode="manual"))
store.create_dataset_contract(DatasetContractConfigCreate(dataset_contract_id="household_account_transactions_v1", dataset_name="household_account_transactions", version=1, allow_extra_columns=False, columns=(DatasetColumnConfig("booked_at", ColumnType.DATE), DatasetColumnConfig("account_id", ColumnType.STRING), DatasetColumnConfig("counterparty_name", ColumnType.STRING), DatasetColumnConfig("amount", ColumnType.DECIMAL), DatasetColumnConfig("currency", ColumnType.STRING), DatasetColumnConfig("description", ColumnType.STRING, required=False))))
store.create_column_mapping(ColumnMappingCreate(column_mapping_id="bank_partner_export_v1", source_system_id="bank_partner_export", dataset_contract_id="household_account_transactions_v1", version=1, rules=(ColumnMappingRule("booked_at", source_column="booking_date"), ColumnMappingRule("account_id", source_column="account_number"), ColumnMappingRule("counterparty_name", source_column="payee"), ColumnMappingRule("amount", source_column="amount_eur"), ColumnMappingRule("currency", default_value="EUR"), ColumnMappingRule("description", source_column="memo"))))
for identifier, name, enabled in [("bank_partner_transactions", "Bank Partner Transactions", True), ("bank_partner_savings", "Bank Partner Savings", True), ("bank_partner_disabled", "Bank Partner Disabled", False)]:
    store.create_source_asset(SourceAssetCreate(source_asset_id=identifier, name=name, source_system_id="bank_partner_export", dataset_contract_id="household_account_transactions_v1", column_mapping_id="bank_partner_export_v1", transformation_package_id="builtin_account_transactions", asset_type="dataset", enabled=enabled))
store.create_source_freshness_config(SourceFreshnessConfigCreate(source_asset_id="bank_partner_transactions", acquisition_mode="manual_export", expected_frequency="ad_hoc", coverage_kind="rolling_period", due_day_of_month=None, expected_window_days=5, freshness_sla_days=40, sensitivity_class="financial", reminder_channel="dashboard", requires_human_action=True))
'''


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


def _stop_pid_group(pid, process=None):
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + 2
    killed = False
    while time.monotonic() < deadline + 10:
        if process is not None:
            process.poll()
        try:
            while os.waitpid(-pid, os.WNOHANG)[0]:
                pass
        except ChildProcessError:
            pass
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            _assert_group_gone(pid)
            return
        if time.monotonic() >= deadline and not killed:
            os.killpg(pid, signal.SIGKILL)
            killed = True
        time.sleep(0.05)
    _assert_group_gone(pid)


def _stop_group(process):
    _stop_pid_group(process.pid, process)


def _stop_browser_groups(log, owned_profile):
    owned = str(owned_profile).encode()
    groups = {int(value) for value in re.findall(r"^OWNED_BROWSER_PID=(\d+)$", log.read_text(errors="replace"), re.MULTILINE)}
    # A killed Node can orphan Chromium before its debug line is flushed. We only
    # inspect adopted children of this subreaper, then match the unique profile.
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            if int(stat[1]) == os.getpid() and owned in (entry / "cmdline").read_bytes():
                groups.add(os.getpgid(int(entry.name)))
        except (ProcessLookupError, PermissionError, FileNotFoundError):
            continue
    for pid in groups:
        try:
            while os.waitpid(-pid, os.WNOHANG)[0]:
                pass
        except ChildProcessError:
            pass
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            _trace("lifecycle", {"event": "browser_group_absent", "pid": pid})
            continue
        members = []
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                stat = (entry / "stat").read_text().rsplit(")", 1)[1].split()
                if os.getpgid(int(entry.name)) == pid and int(stat[1]) == os.getpid():
                    members.append((entry / "cmdline").read_bytes())
            except (ProcessLookupError, PermissionError, FileNotFoundError):
                continue
        if not any(owned in cmd for cmd in members):
            raise RuntimeError(f"browser group {pid} lacks owned profile identity")
        _trace("lifecycle", {"event": "stop_browser_group", "pid": pid})
        _stop_pid_group(pid)


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
        XDG_DATA_HOME=str(data / "xdg-data"),
        XDG_STATE_HOME=str(data / "xdg-state"),
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


def _api_instance(tmp_path_factory):
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


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    yield from _api_instance(tmp_path_factory)


@pytest.fixture
def isolated_api(tmp_path_factory):
    global TRACE_DIR
    old = TRACE_DIR
    try:
        yield from _api_instance(tmp_path_factory)
    finally:
        TRACE_DIR = old


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


def _success_bytes(case):
    return CSV.replace(b"Electric Utility", ("Inline " + case).encode())


def _require_unique(values):
    assert len({hashlib.sha256(value).digest() for value in values}) == len(values)


def test_success_fixtures_do_not_duplicate(isolated_api):
    client, _ = isolated_api
    cases = ("RP1", "RP5", "RP6", "RP-wrong-id", "RP-wrong-path")
    fixtures = [(case + ".csv", _success_bytes(case)) for case in cases]
    fixtures += [("aria.csv", CSV.replace(b"Electric Utility", b"Aria announcement upload")), ("unique.json", JSON_BYTES.replace(b"JSON Utility", b"Browser JSON Utility")), ("unique.xlsx", XLSX[:-2] + b"\x01\x00X")]
    values = [value for _, value in fixtures]
    _require_unique(values)
    with pytest.raises(AssertionError):
        _require_unique([values[0], values[0], values[0]])
    for filename, content in fixtures:
        result = _multipart(client, "/ingest/configured-csv", A, filename, content)
        assert result.status_code == 201, (filename, result.text)
        _detail(client, result.json()["run"]["run_id"], A)


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
    _require_hash(XLSX, "4d12a219dc8a210a2901c8a4415510a1b3c842eb5da7922860cba61877b4f32d")


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
        ("POST", "/ingest/configured-csv"): (ingest_status, ingest_payload if ingest_payload is not None else {"run": {"run_id": "run-1", "status": "landed", "row_count": 1, "raw_path": MARKER, "manifest_path": MARKER, "sha256": MARKER, "diagnostic": MARKER}, "promotion": {"skipped": True, "skip_reason": MARKER, "diagnostic": MARKER}, "diagnostic": MARKER}),
        ("POST", "/ingest/dry-run"): (200, {"preview": {"target": {"source_asset_id": A, "upload_path": "/upload/configured-csv", "confidence_label": "manual"}, "ready": True, "row_count": 1, "issues": [], "detection": {"format": "csv"}}}),
        ("GET", "/runs/run-1"): (run_status, run_payload if run_payload is not None else {"run": {"run_id": "run-1", "context": {"source_asset_id": A}}}),
        ("GET", "/control/source-freshness"): (freshness_status, freshness_payload if freshness_payload is not None else {"datasets": [{"source_asset_id": A, "latest_run_id": "run-1", "freshness_state": "current"}]}),
    }
    for key, (status, payload) in list(upstream.responses.items()):
        if isinstance(payload, dict):
            payload = dict(payload, raw_path=MARKER, manifest_path=MARKER, sha256=MARKER, diagnostic=MARKER)
            upstream.responses[key] = status, payload


def _json_response(response):
    assert not 300 <= response.status_code < 400, response.text
    assert "location" not in response.headers
    assert response.headers.get("content-type", "").startswith("application/json"), response.text
    for marker in ("SECRET_VALUE", "https://sensitive.invalid/trace", "STACKTRACE"):
        assert marker not in response.text
    data = response.json()
    assert isinstance(data, dict)
    for key in ("outcome", "message", "run_id", "status", "freshness_state", "observation", "observed_latest_run_id"):
        if data.get(key) is not None:
            assert isinstance(data[key], str)
    if "ready" in data:
        assert type(data["ready"]) is bool
    if data.get("row_count") is not None:
        assert type(data["row_count"]) is int and data["row_count"] >= 0
    if "issues" in data:
        assert isinstance(data["issues"], list)
    allowed = {"outcome", "message", "run_id", "status", "row_count", "issues", "promotion", "freshness_state", "observation", "observed_latest_run_id", "ready", "target", "detection"}
    assert set(data) <= allowed
    templates = {
        "duplicate_file": "File already exists.",
        "empty_file": "File is empty.",
        "duplicate_column": "Duplicate column.",
        "missing_required_column": "Required column is missing.",
        "unexpected_column": "Unexpected column.",
        "column_count_mismatch": "Column count does not match the header.",
        "invalid_integer": "Invalid integer.",
        "invalid_decimal": "Invalid decimal.",
        "invalid_date": "Invalid date.",
        "invalid_datetime": "Invalid datetime.",
        "invalid_boolean": "Invalid boolean.",
        "unknown": "Validation issue.",
    }
    for issue in data.get("issues", []):
        assert set(issue) <= {"code", "message", "column", "row_number"}
        code = issue["code"]
        column = issue.get("column")
        number = issue.get("row_number")
        if column is not None:
            assert isinstance(column, str) and 0 < len(column) <= 128
            assert all(char.isalnum() or char in " _.-" for char in column)
        if number is not None:
            assert type(number) is int and 1 <= number <= 1_000_000_000
        if code == "missing_required_value":
            assert column is not None
            assert issue["message"] == f"Required value missing for column '{column}'."
        else:
            assert code in templates and issue["message"] == templates[code]
    if data.get("promotion") is not None:
        promotion = data["promotion"]
        assert isinstance(promotion, dict)
        assert set(promotion) <= {"facts_loaded", "marts_refreshed", "publication_keys", "skipped"}
        if promotion.get("facts_loaded") is not None:
            assert type(promotion["facts_loaded"]) is int and promotion["facts_loaded"] >= 0
        if "skipped" in promotion:
            assert type(promotion["skipped"]) is bool
        for key in ("marts_refreshed", "publication_keys"):
            if key in promotion:
                assert isinstance(promotion[key], list) and all(isinstance(value, str) for value in promotion[key])
    if data.get("target") is not None:
        target = data["target"]
        assert isinstance(target, dict) and set(target) <= {"source_asset_id", "upload_path", "confidence_label"}
        assert all(isinstance(value, str) for value in target.values())
    if data.get("detection") is not None:
        detection = data["detection"]
        assert isinstance(detection, dict) and set(detection) <= {"format"}
        assert all(isinstance(value, str) for value in detection.values())
    return data


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
        _assert_observation(payload, case)


def _assert_observation(payload, case):
    assert payload["outcome"] in ("landed", "landed_unconfirmed")
    assert payload["outcome"] != "identity_mismatch"
    assert payload["run_id"] == "run-1"
    assert payload["observation"] == ("superseded" if case == "superseded" else "missing")
    assert payload["observed_latest_run_id"] == ("other-run" if case == "superseded" else None)
    assert payload["freshness_state"] == ("current" if case == "superseded" else None)
    expected = "Run landed. The observed latest run differs." if case == "superseded" else "Run landed. The source freshness row was not returned."
    assert payload["message"] == expected


def test_observation_guard_rejects_ignored_freshness():
    good = {"outcome": "landed", "run_id": "run-1", "observation": "superseded", "observed_latest_run_id": "other-run", "freshness_state": "current", "message": "Run landed. The observed latest run differs."}
    _assert_observation(good, "superseded")
    for field, value in (("observed_latest_run_id", "run-1"), ("observation", "missing"), ("message", "Run is current.")):
        with pytest.raises(AssertionError):
            _assert_observation(dict(good, **{field: value}), "superseded")


def test_response_guard_rejects_raw_spread():
    good = {"outcome": "landed", "run_id": "run-1", "promotion": {"skipped": True}}
    _json_response(httpx.Response(201, json=good))
    for extra in ({"raw_path": "/private"}, {"manifest_path": "/private"}, {"sha256": "hash"}, {"diagnostic": "private"}, {"promotion": {"skip_reason": "private"}}, {"promotion": {"facts_loaded": "one"}}, {"ready": "true"}, {"message": MARKER}):
        with pytest.raises(AssertionError):
            _json_response(httpx.Response(201, json=dict(good, **extra)))
    issue = {"code": "missing_required_value", "message": "Required value missing for column 'amount'.", "column": "amount", "row_number": 2}
    _json_response(httpx.Response(400, json={"issues": [issue]}))
    for fault in ({"message": "untrusted but marker-free"}, {"column": "https://private"}, {"row_number": "2"}, {"code": "private_code"}):
        with pytest.raises(AssertionError):
            _json_response(httpx.Response(400, json={"issues": [dict(issue, **fault)]}))



@pytest.mark.parametrize("status,body,outcome", [(400, {"run": {"run_id": "run-1", "status": "rejected", "issues": [{"code": "unknown", "message": MARKER}]}}, "rejected"), (400, {"detail": MARKER}, "outcome_unknown"), (409, {"run": {"run_id": "run-1", "status": "rejected", "issues": [{"code": "duplicate_file", "message": MARKER}]}}, "duplicate"), (401, {"detail": MARKER}, "auth_required"), (403, {"detail": MARKER}, "forbidden"), (404, {"detail": MARKER}, "outcome_unknown"), (422, {"detail": MARKER}, "outcome_unknown")])
def test_nb6_nb7_nb8_nb9_nb10_safe_errors(next_boundary, status, body, outcome):
    base, upstream = next_boundary
    _script(upstream, ingest_status=status, ingest_payload=body)
    response = _boundary_post(base, f"/sources/{A}/upload")
    payload = _json_response(response)
    _assert_error_outcome(response.status_code, status, body, outcome, payload)
    assert len([call for call in upstream.calls if call[1] == "/ingest/configured-csv"]) == 1


def _assert_error_outcome(actual, status, body, outcome, payload):
    assert actual == status and payload["outcome"] == outcome
    if status in (400, 404, 422) and "run" not in body:
        assert payload["outcome"] == "outcome_unknown"
        assert payload["message"] == "Upload outcome could not be confirmed."
    if status == 400 and "run" in body:
        assert payload["issues"][0]["message"] == "Validation issue."


def test_receiptless_status_guard_rejects_false_certainty():
    good = {"outcome": "outcome_unknown", "message": "Upload outcome could not be confirmed."}
    for status in (400, 404, 422):
        _assert_error_outcome(status, status, {"detail": MARKER}, "outcome_unknown", good)
        for false in ("unknown_source", "malformed_request", "refused"):
            with pytest.raises(AssertionError):
                _assert_error_outcome(status, status, {"detail": MARKER}, false, dict(good, outcome=false))


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


BROWSER_SCRIPT = r'''
const work = process.env.WORK_DIR;
const { chromium } = require(work + "/frontend/node_modules/playwright");
const assert = require("node:assert/strict");
const base = process.env.WEB_BASE;
const mode = process.env.CASE_ID;
const aid = "bank_partner_transactions";
const bid = "bank_partner_savings";
const aName = "Bank Partner Transactions";
const bName = "Bank Partner Savings";
const result = {case: mode, steps: []};
function step(name, data) { result.steps.push({name, data}); console.log("STEP", name, JSON.stringify(data)); }
async function login(browser, role, options = {}) {
const context = await browser.newContext(options);
const page = await context.newPage();
await page.goto(base + "/login");
await page.fill("#username", "acceptance-" + role);
await page.fill("#password", "local-test-password-123");
await Promise.all([page.waitForURL(url => !url.pathname.startsWith("/login")), page.click("button[type=submit]")]);
return {context, page};
}
async function row(page, name) {
const row = page.getByRole("row").filter({hasText: name});
assert.equal(await row.count(), 1, "expected exactly one named source row: " + name);
return row;
}
async function href(row) {
const link = row.locator('a[href^="/runs/"]');
assert.equal(await link.count(), 1, "expected exactly one run link in row");
return await link.getAttribute("href");
}
async function prepare(page, name, filename) {
const r = await row(page, name);
const preflight = page.waitForResponse(response => response.url().includes("/dry-run") && response.request().method() === "POST");
await r.locator('input[type="file"]').setInputFiles(work + "/" + filename);
await preflight;
return r;
}
(async () => {
const server = await chromium.launchServer({host: "127.0.0.1", port: 0, headless: true, args: ["--no-sandbox"]});
console.log("OWNED_BROWSER_PID=" + server.process().pid);
const browser = await chromium.connect(server.wsEndpoint());
try {
if (mode === "guard-native-failure") {
console.log("GUARD_BROWSER_READY");
await new Promise(() => {});
} else if (mode === "guard-fault-rewrite") {
const {context, page} = await login(browser, "admin");
await page.goto(base + "/upload");
const input = require("node:fs").readFileSync(work + "/RP-wrong-id.csv", "utf8");
for (const fault of ["id", "path"]) {
let calls = 0;
await page.route("**/upload/dry-run", async route => {
const real = await route.fetch();
const body = await real.json();
assert.equal(body.preview.ready, true);
assert.equal(body.preview.target.source_asset_id, aid);
assert.equal(body.preview.target.upload_path, "/upload/configured-csv");
if (fault === "id") body.preview.target.source_asset_id = bid;
else body.preview.target.upload_path = "/upload/subscriptions";
calls++;
await route.fulfill({response: real, json: body});
});
const body = await page.evaluate(async ({input, aid}) => {
const form = new FormData();
form.append("file", new File([input], "guard.csv", {type: "text/csv"}));
form.append("upload_path", "/upload/configured-csv");
form.append("source_asset_id", aid);
return await (await fetch("/upload/dry-run", {method: "POST", body: form})).json();
}, {input, aid});
assert.equal(calls, 1);
assert.equal(body.preview.ready, true);
assert.equal(body.preview.target.source_asset_id, fault === "id" ? bid : aid);
assert.equal(body.preview.target.upload_path, fault === "path" ? "/upload/subscriptions" : "/upload/configured-csv");
await page.unroute("**/upload/dry-run");
step("fault-rewrite", fault);
}
await context.close();
} else if (mode === "positive") {
const admin = await login(browser, "admin");
await admin.page.goto(base + "/sources");
const ar = await row(admin.page, aName);
const br = await row(admin.page, bName);
const ah = await href(ar);
const bh = await href(br);
step("row-hrefs", {a: ah, b: bh, expectedA: process.env.RUN_A, expectedB: process.env.RUN_B});
assert.equal(ah, "/runs/" + process.env.RUN_A);
assert.equal(bh, "/runs/" + process.env.RUN_B);
await admin.page.goto(base + "/upload");
const form = admin.page.locator('form[action="/upload/configured-csv"]');
await form.locator('select[name="source_asset_id"]').selectOption(aid);
await form.locator('input[name="file"]').setInputFiles(work + "/normal.csv");
const [response] = await Promise.all([admin.page.waitForResponse(r => r.url().includes("/upload/configured-csv") && r.request().method() === "POST"), form.getByRole("button", {name: "Upload file"}).click()]);
step("ordinary-upload", {status: response.status(), location: response.headers().location});
assert.equal(response.status(), 303);
await admin.page.waitForURL(/\/ingest-summary\//);
await admin.context.close();
const reader = await login(browser, "reader");
await reader.page.goto(base + "/sources");
await reader.page.waitForURL(url => url.pathname === "/");
step("reader-url", reader.page.url());
assert.equal(new URL(reader.page.url()).pathname, "/");
await reader.context.close();
const operator = await login(browser, "operator");
await operator.page.goto(base + "/sources");
const text = await operator.page.locator("body").innerText();
step("operator", text);
assert.match(text, /couldn't load|something went wrong/i);
await operator.context.close();
} else if (mode === "RP-nojs") {
const {context, page} = await login(browser, "admin", {javaScriptEnabled: false});
await page.goto(base + "/sources");
assert.equal(new URL(page.url()).pathname, "/sources");
const rawRows = page.locator("tr").filter({hasText: aName});
const rawCount = await rawRows.count();
step("no-js-dom", {rawCount, html: await page.content()});
assert.equal(rawCount, 1, "seeded row absent from raw no-JS DOM; inline behavior unobservable");
const posts = [];
const harmless = [];
await page.route("**/*", async route => {
if (route.request().method() !== "POST") { await route.continue(); return; }
const path = new URL(route.request().url()).pathname;
const changes = /^(\/sources\/|\/ingest\/|\/upload\/)/.test(path) && !path.endsWith("/dry-run");
(changes ? posts : harmless).push(path);
await route.abort();
});
let attempted = 0;
for (const form of await rawRows.locator("form").all()) {
for (const file of await form.locator('input[type="file"]').all()) {
if (await file.isEnabled()) await file.setInputFiles(work + "/RP1.csv");
}
for (const field of await form.locator('input[required]:not([type="file"]):not([type="hidden"])').all()) {
if (await field.isVisible() && await field.isEnabled() && !(await field.inputValue())) await field.fill("synthetic");
}
for (const submit of await form.locator('button:not([type]),button[type="submit"],input[type="submit"]').all()) {
if (await submit.isVisible() && await submit.isEnabled()) { attempted++; await submit.click({timeout: 3000}); }
}
}
await page.waitForTimeout(250);
step("no-js", {rowVisible: await rawRows.isVisible(), attempted, posts, harmless});
assert.deepEqual(posts, [], "native row control attempted mutation without JS preflight");
await context.close();
} else {
const {context, page} = await login(browser, "admin");
await page.goto(base + "/sources");
await page.evaluate(() => {window.__hla1587_marker = "same-page";});
const ar = await row(page, aName);
const br = await row(page, bName);
const beforeA = await href(ar);
const beforeB = await href(br);
const named = ar.getByRole("button", {name: "Upload to " + aName});
assert.equal(await named.count(), 1, "missing inline upload control on named row");
const requests = [];
page.on("request", request => {
const path = new URL(request.url()).pathname;
if (request.method() === "POST" && /^(\/sources\/|\/ingest\/|\/upload\/)/.test(path) && !path.endsWith("/dry-run")) requests.push(request.url());
});
if (mode === "RP7") {
const disabled = await row(page, "Bank Partner Disabled");
assert.equal(await disabled.locator('input[type="file"]').count(), 0);
assert.equal(await disabled.getByRole("button", {name: /upload/i}).count(), 0);
} else if (mode === "RP10") {
await prepare(page, aName, "aria.csv");
const live = ar.locator('[aria-live]');
assert.ok(await live.count());
const receiptPromise = page.waitForResponse(r => r.url().endsWith("/upload") && r.request().method() === "POST");
await named.click();
const receipt = await (await receiptPromise).json();
assert.ok(receipt.run_id);
await live.getByText(/landed|uploaded/i).waitFor({timeout: 10000});
await page.waitForFunction(id => document.querySelector(`a[href="/runs/${id}"]`), receipt.run_id);
assert.equal(await href(ar), "/runs/" + receipt.run_id);
assert.equal(requests.length, 1);
assert.ok(requests[0].endsWith("/upload"));
} else {
let filename = mode === "RP2-xlsx" ? "unique.xlsx" : mode === "RP2-json" ? "unique.json" : mode === "RP3" ? "invalid.csv" : mode + ".csv";
if (mode === "RP4") filename = "duplicate.csv";
if (mode === "RP5") {
let delayed = false;
const dryResponses = [];
page.on("response", response => {
if (response.url().includes("/sources/") && response.url().endsWith("/dry-run")) dryResponses.push(response.request().postData() || "");
});
await page.route("**/sources/**/dry-run", async route => {
if (!delayed) { delayed = true; await new Promise(resolve => setTimeout(resolve, 1200)); }
await route.continue();
});
await ar.locator('input[type="file"]').setInputFiles(work + "/invalid.csv");
await ar.locator('input[type="file"]').setInputFiles(work + "/RP5.csv");
await page.waitForTimeout(1600);
assert.equal(dryResponses.length, 2, "both real preflights must finish");
assert.match(dryResponses[0], /RP5.csv/);
assert.match(dryResponses[1], /invalid.csv/);
assert.ok(await named.isEnabled(), "older nonready preview replaced the latest ready file");
} else {
let faults = 0;
if (mode.startsWith("RP-wrong-")) await page.route("**/sources/**/dry-run", async route => {
const real = await route.fetch();
const body = await real.json();
assert.equal(body.ready, true);
assert.equal(body.target.source_asset_id, aid);
assert.equal(body.target.upload_path, "/upload/configured-csv");
if (mode === "RP-wrong-id") body.target.source_asset_id = bid;
else body.target.upload_path = "/upload/subscriptions";
faults++;
await route.fulfill({response: real, json: body});
});
await prepare(page, mode === "RP4" ? bName : aName, filename);
if (mode.startsWith("RP-wrong-")) {
assert.equal(faults, 1);
await page.waitForTimeout(300);
assert.ok(await named.count() === 0 || await named.isDisabled());
assert.equal(requests.length, 0);
}
}
if (mode.startsWith("RP-wrong-")) {
assert.equal(requests.length, 0);
} else if (mode === "RP3") {
assert.ok(await named.isDisabled());
assert.match(await ar.innerText(), /issue|required|invalid/i);
assert.equal(requests.length, 0);
} else {
const target = mode === "RP4" ? br : ar;
const button = target.getByRole("button", {name: "Upload to " + (mode === "RP4" ? bName : aName)});
await button.waitFor({state: "visible"});
if (mode === "RP6") await page.route("**/sources/**/upload", async route => {await new Promise(resolve => setTimeout(resolve, 800)); await route.continue();});
const receiptPromise = page.waitForResponse(r => r.url().endsWith("/upload") && r.request().method() === "POST");
if (mode === "RP6") await button.dblclick();
else await button.click();
const receipt = await (await receiptPromise).json();
assert.ok(receipt.run_id);
await page.waitForFunction(id => document.querySelector(`a[href="/runs/${id}"]`), receipt.run_id);
assert.equal(await href(target), "/runs/" + receipt.run_id);
await page.waitForTimeout(500);
assert.equal(requests.length, 1);
assert.ok(requests[0].endsWith("/upload"));
assert.equal(new URL(page.url()).pathname, "/sources");
assert.equal(await page.evaluate(() => window.__hla1587_marker), "same-page");
const text = await target.innerText();
if (mode === "RP4") assert.match(text, /duplicate|already/i);
else {
assert.match(text, /landed|uploaded/i);
assert.notEqual(await href(ar), beforeA);
assert.equal(await href(br), beforeB);
}
}
}
step("feature-observation", {mode, requests, beforeA, beforeB, url: page.url()});
await context.close();
}
} finally {
await browser.close();
await server.close();
console.log("RESULT", JSON.stringify(result));
}
})().catch(error => {console.error(error.stack || String(error)); process.exit(1);});
'''


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
    for case in ("RP1", "RP5", "RP6", "RP-wrong-id", "RP-wrong-path"):
        (work / (case + ".csv")).write_bytes(_success_bytes(case))
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


def _run_browser(command, env, log, *, native, force_failure=False):
    libc = ctypes.CDLL(None)
    prior = ctypes.c_int()
    assert libc.prctl(37, ctypes.byref(prior), 0, 0, 0) == 0
    assert libc.prctl(36, 1, 0, 0, 0) == 0
    process = None
    log.write_text("COMMAND " + repr(command) + "\n")
    try:
        with log.open("ab") as output:
            process = subprocess.Popen(command, env=env, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            _trace("lifecycle", {"event": "start_browser", "pid": process.pid, "pgid": process.pid})
            if force_failure:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline and "GUARD_BROWSER_READY" not in log.read_text(errors="replace"):
                    assert process.poll() is None, log.read_text(errors="replace")
                    time.sleep(0.05)
                text = log.read_text(errors="replace")
                pids = re.findall(r"^OWNED_BROWSER_PID=(\d+)$", text, re.MULTILINE)
                assert "GUARD_BROWSER_READY" in text and pids, text
                os.killpg(int(pids[-1]), signal.SIGSTOP)
                os.kill(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
                os.killpg(int(pids[-1]), 0)
                _trace("guard", {"node_killed": process.pid, "browser_alive": int(pids[-1])})
                raise RuntimeError("forced native browser failure")
            process.wait(timeout=120)
        with log.open("a") as output:
            output.write("\nEXIT " + str(process.returncode) + "\n")
        return process.returncode
    finally:
        try:
            if process is not None:
                _stop_group(process)
        finally:
            try:
                if native:
                    _stop_browser_groups(log, env["TMPDIR"])
            finally:
                assert libc.prctl(36, prior.value, 0, 0, 0) == 0


def _browser_case(real_page, case):
    base, work, run_ids, client = real_page
    before = _population(client)
    before_rows = _rows(client)
    name = "hla1587-" + uuid.uuid4().hex
    env = _environment(work / ("browser-env-" + name), _port())
    preferred = Path("/projects/dev/homelab-analytics/.tooling/node-v20.20.1-linux-x64/bin")
    if preferred.is_dir():
        env["PATH"] = str(preferred) + os.pathsep + env.get("PATH", "")
    env["PLAYWRIGHT_BROWSERS_PATH"] = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or str(Path.home() / ".cache/ms-playwright")
    env["DEBUG"] = "pw:browser"
    probe_command = ["node", "-e", "const p=require('./node_modules/playwright');(async()=>{const b=await p.chromium.launchServer({host:'127.0.0.1',port:0,headless:true,args:['--no-sandbox']});console.log('OWNED_BROWSER_PID='+b.process().pid);await b.close()})().catch(e=>{console.error(e);process.exit(1)})"]
    probe_log = work / ("native-probe-" + name + ".log")
    # The probe resolves Playwright from the copied frontend.
    probe_command[2] = probe_command[2].replace("./node_modules/playwright", str(work / "frontend/node_modules/playwright"))
    probe_exit = _run_browser(probe_command, env, probe_log, native=True)
    native = probe_exit == 0 and (case == "guard-native-failure" or not os.environ.get("HLA_FORCE_BROWSER_FALLBACK"))
    if case == "guard-native-failure":
        assert native, probe_log.read_text()
    env.update(WEB_BASE=base, CASE_ID=case, RUN_A=run_ids[0], RUN_B=run_ids[1])
    if native:
        env["WORK_DIR"] = str(work)
        command = ["node", str(work / "browser.cjs")]
    else:
        command = ["docker", "run", "--pull=never", "--name", name, "--label", "hla.acceptance=" + name, "--network", "host", "-v", str(work) + ":/work:ro", "-e", "WORK_DIR=/work", "-e", "WEB_BASE=" + base, "-e", "CASE_ID=" + case, "-e", "RUN_A=" + run_ids[0], "-e", "RUN_B=" + run_ids[1], "sha256:b0ab6f3cb99aa7803adbc14d9027ec1785fc6e433b97e134e0f8fe61683b6b53", "node", "/work/browser.cjs"]
    evidence = work / ("browser-" + case + "-" + name + ".log")
    try:
        exit_code = _run_browser(command, env, evidence, native=native, force_failure=case == "guard-native-failure")
        output = evidence.read_text(errors="replace")
        assert exit_code == 0, output
        assert "RESULT " in output, output
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
        if case in ("RP3", "RP7", "RP-nojs", "RP-wrong-id", "RP-wrong-path", "guard-fault-rewrite"):
            assert after == before, (case, before, after)
    finally:
        if not native:
            cleanup = subprocess.run(["docker", "rm", "-f", name], env=env, capture_output=True, text=True, timeout=30)
            inspect = subprocess.run(["docker", "ps", "-a", "--filter", "name=^/" + name + "$", "--format", "{{.ID}}"], env=env, capture_output=True, text=True, timeout=30)
            with evidence.open("a") as stream:
                stream.write("\nCLEANUP " + repr((cleanup.returncode, cleanup.stdout, cleanup.stderr, inspect.returncode, inspect.stdout, inspect.stderr)))
            assert inspect.returncode == 0 and not inspect.stdout.strip(), evidence.read_text()


def test_real_preflight_fault_rewrite_is_closed(real_page):
    _browser_case(real_page, "guard-fault-rewrite")


def test_rp8_rp9_and_page_positive_controls(real_page):
    _browser_case(real_page, "positive")


@pytest.mark.parametrize("case", ["RP1", "RP2-xlsx", "RP2-json", "RP3", "RP4", "RP5", "RP6", "RP7", "RP10", "RP-nojs", "RP-wrong-id", "RP-wrong-path"])
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
    assert payload["issues"][0]["message"] == "Required value missing for column 'amount'."
    assert MARKER not in json.dumps(payload)


@pytest.mark.parametrize("latest", ["old-run", "different-run"])
def test_nb7_no_receipt_never_attributes_latest_pointer(next_boundary, latest):
    base, upstream = next_boundary
    _script(upstream, ingest_status=400, ingest_payload={"error": MARKER}, freshness_payload={"datasets": [{"source_asset_id": A, "latest_run_id": latest, "freshness_state": "current"}]})
    result = _boundary_post(base, f"/sources/{A}/upload", {"expected_prior_run_id": "old-run"})
    payload = _json_response(result)
    assert result.status_code == 400 and payload["outcome"] == "outcome_unknown"
    assert payload["observed_latest_run_id"] == latest
    assert payload["observation"] == "observed"
    assert payload["freshness_state"] == "current"
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


def test_cleanup_kills_surviving_child_after_leader_exit(tmp_path):
    libc = ctypes.CDLL(None)
    prior = ctypes.c_int()
    assert libc.prctl(37, ctypes.byref(prior), 0, 0, 0) == 0
    assert libc.prctl(36, 1, 0, 0, 0) == 0
    ready = tmp_path / "child-ready"
    child = "import signal,time,pathlib,sys;signal.signal(signal.SIGTERM,signal.SIG_IGN);pathlib.Path(sys.argv[1]).write_text('ready');time.sleep(60)"
    leader = "import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]);time.sleep(60)"
    process = subprocess.Popen([sys.executable, "-c", leader, child, str(ready)], start_new_session=True)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists()
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
        with pytest.raises(RuntimeError):
            _assert_group_gone(process.pid)
        _trace("guard", {"leader_exit": process.returncode, "surviving_group": process.pid})
        _stop_group(process)
        _assert_group_gone(process.pid)
    finally:
        _stop_group(process)
        assert libc.prctl(36, prior.value, 0, 0, 0) == 0


def test_native_browser_failure_finalizer_stops_group(real_page):
    with pytest.raises(RuntimeError, match="forced native browser failure"):
        _browser_case(real_page, "guard-native-failure")


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


EXPECTED_CASES = (
    "test_receiptless_status_guard_rejects_false_certainty",
    "test_real_preflight_fault_rewrite_is_closed",
    'test_observation_guard_rejects_ignored_freshness',
    'test_response_guard_rejects_raw_spread',
    'test_cleanup_kills_surviving_child_after_leader_exit',
    'test_native_browser_failure_finalizer_stops_group',
    'test_success_fixtures_do_not_duplicate',
    'test_rp_inline_feature[RP-wrong-id]',
    'test_rp_inline_feature[RP-wrong-path]',
    'test_rp_inline_feature[RP-nojs]',
    'test_nb17_availability_states[free_string-words6]',
    'test_rb_opaque_source_identity',
    'test_nb_opaque_source_identity[dry-run]',
    'test_nb_opaque_source_identity[upload]',
    'test_nb17_availability_states[empty-words5]',
    'test_rb1_csv_pinned_identity_and_sibling',
    'test_rb2_xlsx',
    'test_rb3_json_detection_is_advisory',
    'test_rb4_duplicate_records_sibling_run',
    'test_rb5_invalid_dry_run_and_ingest',
    'test_rb6_corrupt_xlsx_and_xls',
    'test_rb7_disabled_asset',
    'test_rb9_permissions',
    'test_rb10_dry_run_does_not_create_run',
    'test_fixture_hashes_are_stable',
    'test_rb11_shared_mapping_uses_explicit_asset',
    'test_rb8_catalog_and_users_unchanged_by_dry_run',
    'test_nb15_existing_upload_redirect_positive_control',
    'test_nb1_nb2_path_binding_and_forwarding[dry-run-/ingest/dry-run]',
    'test_nb1_nb2_path_binding_and_forwarding[upload-/ingest/configured-csv]',
    'test_nb3_landed_reports_observed_freshness[current]',
    'test_nb3_landed_reports_observed_freshness[unconfigured]',
    'test_nb4_nb5_context_and_observation[wrong_context]',
    'test_nb4_nb5_context_and_observation[superseded]',
    'test_nb4_nb5_context_and_observation[missing_row]',
    'test_nb4_nb5_context_and_observation[read_500]',
    'test_nb4_nb5_context_and_observation[read_403]',
    'test_nb4_nb5_context_and_observation[read_reset]',
    'test_nb6_nb7_nb8_nb9_nb10_safe_errors[400-body0-rejected]',
    'test_nb6_nb7_nb8_nb9_nb10_safe_errors[400-body1-outcome_unknown]',
    'test_nb6_nb7_nb8_nb9_nb10_safe_errors[409-body2-duplicate]',
    'test_nb6_nb7_nb8_nb9_nb10_safe_errors[401-body3-auth_required]',
    'test_nb6_nb7_nb8_nb9_nb10_safe_errors[403-body4-forbidden]',
    'test_nb6_nb7_nb8_nb9_nb10_safe_errors[404-body5-outcome_unknown]',
    'test_nb6_nb7_nb8_nb9_nb10_safe_errors[422-body6-outcome_unknown]',
    'test_nb11_malformed_outcome_unknown[not json SECRET_VALUE https://sensitive.invalid/trace STACKTRACE]',
    'test_nb11_malformed_outcome_unknown[payload1]',
    'test_nb12_transport_failure',
    'test_nb13_missing_file_makes_no_upstream_call[dry-run]',
    'test_nb13_missing_file_makes_no_upstream_call[upload]',
    'test_nb16_dry_run_status_and_transport',
    'test_rp8_rp9_and_page_positive_controls',
    'test_rp_inline_feature[RP1]',
    'test_rp_inline_feature[RP2-xlsx]',
    'test_rp_inline_feature[RP2-json]',
    'test_rp_inline_feature[RP3]',
    'test_rp_inline_feature[RP4]',
    'test_rp_inline_feature[RP5]',
    'test_rp_inline_feature[RP6]',
    'test_rp_inline_feature[RP7]',
    'test_rp_inline_feature[RP10]',
    'test_nb17_availability_states[disabled-words0]',
    'test_nb17_availability_states[source_system_disabled-words1]',
    'test_nb17_availability_states[unsupported-words2]',
    'test_nb17_availability_states[not_found-words3]',
    'test_nb17_availability_states[config_unavailable-words4]',
    'test_nb6_known_issue_context_is_safe',
    'test_nb7_no_receipt_never_attributes_latest_pointer[old-run]',
    'test_nb7_no_receipt_never_attributes_latest_pointer[different-run]',
    'test_identity_guard_rejects_wrong_source',
    'test_guards_fail_closed_on_wrong_hash_and_live_group',
    'test_failed_npm_is_an_infrastructure_error',
    'test_unavailable_api_is_not_semantic_red',
    'test_nb16_dry_run_sanitizes_issue_context',
    'test_self_cli_rejects_missing_population',
)


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
