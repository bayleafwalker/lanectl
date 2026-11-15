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
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
import zlib
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
import pytest

ROOT = Path.cwd()
TRACE_DIR = None
A = "bank_partner_transactions"
B = "bank_partner_savings"
C = "bank_partner_overdue"
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
from datetime import datetime
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
for identifier, name, enabled in [("bank_partner_transactions", "Bank Partner Transactions", True), ("bank_partner_savings", "Bank Partner Savings", True), ("bank_partner_disabled", "Bank Partner Disabled", False), ("bank_partner_overdue", "Bank Partner Overdue", True)]:
    store.create_source_asset(SourceAssetCreate(source_asset_id=identifier, name=name, source_system_id="bank_partner_export", dataset_contract_id="household_account_transactions_v1", column_mapping_id="bank_partner_export_v1", transformation_package_id="builtin_account_transactions", asset_type="dataset", enabled=enabled))
store.create_source_freshness_config(SourceFreshnessConfigCreate(source_asset_id="bank_partner_transactions", acquisition_mode="manual_export", expected_frequency="ad_hoc", coverage_kind="rolling_period", due_day_of_month=None, expected_window_days=5, freshness_sla_days=40, sensitivity_class="financial", reminder_channel="dashboard", requires_human_action=True))
store.create_source_freshness_config(SourceFreshnessConfigCreate(source_asset_id="bank_partner_overdue", acquisition_mode="manual_export", expected_frequency="monthly", coverage_kind="rolling_period", due_day_of_month=1, expected_window_days=0, freshness_sla_days=40, sensitivity_class="financial", reminder_channel="dashboard", requires_human_action=True))
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
    env = {key: os.environ[key] for key in allowed if os.environ.get(key)}
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
    zones = ("Etc/GMT+12", "Etc/GMT-14")
    choices = [(zone, datetime.now(ZoneInfo(zone))) for zone in zones]
    eligible = [(zone, now) for zone, now in choices if now.day > 1]
    assert eligible, "no non-boundary API timezone available"
    zone, local_now = max(eligible, key=lambda item: 23 * 60 + 59 - item[1].hour * 60 - item[1].minute)
    _trace("fixture", {"timezone": zone, "local_date": local_now.date().isoformat()})
    env.update(
        TZ=zone,
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
        admin._hla_fixture_data = data
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
    value = CSV.replace(b"Electric Utility", ("Inline " + case).encode())
    if case == "RP1":
        value += b"2026-01-04,CHK-001,Unique Third,-3.00,Extra row\n"
    return value


def _require_unique(values):
    assert len({hashlib.sha256(value).digest() for value in values}) == len(values)


def test_success_fixtures_do_not_duplicate(isolated_api):
    client, _ = isolated_api
    cases = ("RP1", "RP5", "RP6", "RP-stale", "RP-wrong-id", "RP-wrong-path")
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


def _run_build(name, command, cwd, env, work, timeout=600):
    libc = ctypes.CDLL(None)
    prior = ctypes.c_int()
    assert libc.prctl(37, ctypes.byref(prior), 0, 0, 0) == 0
    assert libc.prctl(36, 1, 0, 0, 0) == 0
    output = work / (name + ".log")
    metadata = work / (name + ".ownership.json")
    process = None
    state = {"command": command}
    try:
        with output.open("wb") as stream:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            state.update(pid=process.pid, pgid=process.pid)
            _trace("lifecycle", {"event": "start_" + name, "pid": process.pid, "pgid": process.pid, "command": command})
            try:
                state["inner_exit"] = process.wait(timeout=timeout)
                try:
                    os.killpg(process.pid, 0)
                    state["group_alive_after_leader"] = True
                except ProcessLookupError:
                    state["group_alive_after_leader"] = False
            except subprocess.TimeoutExpired:
                state["timeout"] = True
                raise
            finally:
                metadata.write_text(json.dumps(state, indent=2) + "\n")
                _stop_group(process)
                state["group_absent"] = True
                metadata.write_text(json.dumps(state, indent=2) + "\n")
        (work / (name + ".exit")).write_text(str(state["inner_exit"]) + "\n")
        return state["inner_exit"]
    finally:
        if process is not None and process.poll() is None:
            _stop_group(process)
        assert libc.prctl(36, prior.value, 0, 0, 0) == 0


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
        exit_code = _run_build(name, command, frontend, env, work)
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
        assert payload["outcome"] == "identity_mismatch" and payload["run_id"] == "run-1" and payload["status"] == "landed"
        assert payload["message"] == "Run recorded; source identity differs."
        assert payload.get("freshness_state") is None and payload.get("promotion") is None
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


@pytest.mark.parametrize("status", [400, 409])
@pytest.mark.parametrize("identity", ["match", "contradiction", "forbidden", "reset"])
def test_rejected_receipt_requires_actual_source_context(next_boundary, status, identity):
    base, upstream = next_boundary
    body = {"run": {"run_id": "run-1", "status": "rejected", "issues": [{"code": "unknown", "message": MARKER}]}}
    context = B if identity == "contradiction" else A
    _script(upstream, ingest_status=status, ingest_payload=body, run_payload={"run": {"run_id": "run-1", "context": {"source_asset_id": context}}})
    if identity == "forbidden":
        upstream.responses[("GET", "/runs/run-1")] = (403, {"detail": MARKER})
    if identity == "reset":
        upstream.responses[("GET", "/runs/run-1")] = (500, None)
    result = _boundary_post(base, f"/sources/{A}/upload")
    payload = _json_response(result)
    assert result.status_code == status
    assert len([call for call in upstream.calls if call[1] == "/runs/run-1"]) == 1
    _assert_rejected_receipt(payload, status, identity)


def _assert_rejected_receipt(payload, status, identity):
    assert payload["run_id"] == "run-1" and payload["status"] == "rejected"
    if identity == "match":
        assert payload["outcome"] == ("rejected" if status == 400 else "duplicate")
    elif identity == "contradiction":
        assert payload["outcome"] == "identity_mismatch"
        assert payload["message"] == "Run recorded; source identity differs."
        assert payload.get("freshness_state") is None and payload.get("promotion") is None
    else:
        assert payload["outcome"] == "identity_unconfirmed"
        assert payload["message"] == "Run recorded; source identity could not be confirmed."
        assert payload.get("freshness_state") is None and payload.get("promotion") is None


def test_rejected_receipt_context_guard_rejects_false_identity():
    good = {"run_id": "run-1", "status": "rejected", "outcome": "identity_mismatch", "message": "Run recorded; source identity differs."}
    _assert_rejected_receipt(good, 400, "contradiction")
    for fault in ({"outcome": "rejected"}, {"run_id": "other"}, {"freshness_state": "current"}, {"promotion": {"skipped": False}}):
        with pytest.raises(AssertionError):
            _assert_rejected_receipt(dict(good, **fault), 400, "contradiction")


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
const cName = "Bank Partner Overdue";
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
await row.first().waitFor({state: "attached", timeout: 15000});
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
const response = await preflight;
return await response.json();
}
function visiblePreviewFacts(text, filename, rowCount) {
const countFirst = new RegExp("\\b" + rowCount + "\\s*(?:rows?|records?)\\b", "i");
const labelFirst = new RegExp("\\b(?:rows?|records?)\\s*[:=]?\\s*" + rowCount + "\\b", "i");
return text.includes(filename) && (countFirst.test(text) || labelFirst.test(text));
}
function visibleAmbiguity(text) {
const clauses = text.split(/(?<=[.!?])\s+|\n+/).filter(Boolean);
return clauses.some((clause, index) => {
const nearby = clause + " " + (clauses[index + 1] || "");
return /(?:shared|same|multiple|more than one|other)/i.test(nearby) && /(?:format|mapping|columns)/i.test(nearby) && /(?:account|source)/i.test(nearby) && /(?:cannot|can't|does not|doesn't|not identify|not determine|confirm|verify|check|belongs)/i.test(nearby);
});
}
async function assertVisiblePreview(page, target, name, filename, preview) {
assert.equal(preview.ready, true);
assert.equal(typeof preview.row_count, "number");
assert.ok(preview.row_count > 0);
let visible = "";
let explanation = "";
const deadline = Date.now() + 10000;
do {
visible = await target.innerText();
explanation = await page.locator("body").innerText();
if (visiblePreviewFacts(visible, filename, preview.row_count) && visibleAmbiguity(explanation)) break;
await page.waitForTimeout(100);
} while (Date.now() < deadline);
assert.ok(visiblePreviewFacts(visible, filename, preview.row_count), visible);
assert.ok(visibleAmbiguity(explanation), explanation);
step("visible-preview", {name, filename, text: visible});
}
async function exerciseNoJsRow(page, rawRows) {
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
const controls = rawRows.locator("button,input");
for (const submit of await controls.all()) {
if (!(await submit.isVisible()) || !(await submit.isEnabled())) continue;
const kind = await submit.evaluate(element => {
if (element instanceof HTMLButtonElement && element.type === "submit") return "submit";
if (element instanceof HTMLInputElement && ["submit", "image"].includes(element.type)) return "submit";
if (element instanceof HTMLInputElement && ["text", "search", "email", "url", "tel", "password", "number"].includes(element.type)) return "enter";
return "other";
});
if (kind === "other") continue;
const handle = await submit.elementHandle();
if (!(await submit.evaluate(element => !!element.form))) continue;
for (const file of await page.locator('input[type="file"]').all()) {
if (await file.evaluate((element, owner) => element.form === owner.form, handle) && await file.isEnabled()) await file.setInputFiles(work + "/RP1.csv");
}
for (const field of await page.locator('input[required]:not([type="file"]):not([type="hidden"])').all()) {
if (await field.evaluate((element, owner) => element.form === owner.form, handle) && await field.isVisible() && await field.isEnabled() && !(await field.inputValue())) await field.fill("synthetic");
}
attempted++;
if (kind === "submit") await submit.click({timeout: 3000});
else await submit.press("Enter", {timeout: 3000});
}
await page.waitForTimeout(250);
return {attempted, posts, harmless};
}
(async () => {
const server = await chromium.launchServer({host: "127.0.0.1", port: 0, headless: true, args: ["--no-sandbox"]});
console.log("OWNED_BROWSER_PID=" + server.process().pid);
const browser = await chromium.connect(server.wsEndpoint());
try {
if (mode === "guard-browser-failure") {
console.log("GUARD_BROWSER_READY");
await new Promise(() => {});
} else if (mode === "guard-visible-preview") {
const context = await browser.newContext();
const page = await context.newPage();
await page.setContent("<div>Validated file: RP1.csv. Rows: 3</div>");
const text = await page.locator("div").innerText();
assert.ok(visiblePreviewFacts(text, "RP1.csv", 3));
assert.ok(visiblePreviewFacts("RP1.csv: 3 records", "RP1.csv", 3));
assert.equal(visiblePreviewFacts(text, "RP1.csv", 2), false);
assert.equal(visiblePreviewFacts("Validated file: RP1.csv", "RP1.csv", 3), false);
assert.equal(visiblePreviewFacts("Validated file: other.csv. Rows: 3", "RP1.csv", 3), false);
assert.ok(visibleAmbiguity("The same format may be used by multiple accounts. Confirm your selected source."));
assert.equal(visibleAmbiguity("Other sources. Columns: 5. Check source status."), false);
step("visible-preview-fault", {text, valid: true, wrongCount: false, absentCount: false, wrongFile: false, coherentWarning: true, unrelatedTokens: false});
await context.close();
} else if (mode === "guard-nojs-external-form") {
const context = await browser.newContext({javaScriptEnabled: false});
const page = await context.newPage();
await page.setContent(`<form id="external" action="${base}/sources/synthetic/upload" method="post" enctype="multipart/form-data"></form><table><tr><td>synthetic source<input type="file" name="file" form="external"><button form="external" type="submit">Upload</button></td></tr></table>`);
const observation = await exerciseNoJsRow(page, page.locator("tr"));
step("no-js-external-fault", observation);
assert.equal(observation.attempted, 1);
assert.deepEqual(observation.posts, ["/sources/synthetic/upload"]);
await context.close();
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
const cr = await row(admin.page, cName);
assert.equal(await href(cr), "/runs/" + process.env.RUN_C);
assert.match(await cr.innerText(), /stale/i);
step("stale-before", {href: await href(cr), text: await cr.innerText()});
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
const observation = await exerciseNoJsRow(page, rawRows);
step("no-js", {rowVisible: await rawRows.isVisible(), ...observation});
assert.deepEqual(observation.posts, [], "native row control attempted mutation without JS preflight");
await context.close();
} else {
const {context, page} = await login(browser, "admin");
await page.goto(base + "/sources");
await page.evaluate(() => {window.__hla1587_marker = "same-page";});
const ar = await row(page, aName);
const br = await row(page, bName);
const beforeA = await href(ar);
const beforeB = await href(br);
const cr = mode === "RP-stale" ? await row(page, cName) : null;
if (cr) {
assert.equal(await href(cr), "/runs/" + process.env.RUN_C);
assert.match(await cr.innerText(), /stale/i);
step("stale-before", {href: await href(cr), text: await cr.innerText()});
}
const namedRow = cr || ar;
const namedName = cr ? cName : aName;
const named = namedRow.getByRole("button", {name: "Upload to " + namedName});
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
const preview = await prepare(page, aName, "aria.csv");
assert.equal(preview.target.source_asset_id, aid);
await assertVisiblePreview(page, ar, aName, "aria.csv", preview);
const live = ar.locator('[aria-live]');
assert.ok(await live.count());
const receiptPromise = page.waitForResponse(r => r.url().endsWith("/upload") && r.request().method() === "POST");
await named.click();
const receipt = await (await receiptPromise).json();
assert.equal(typeof receipt.run_id, "string");
assert.ok(receipt.run_id.length > 0 && receipt.run_id.length <= 256);
step("receipt", {runId: receipt.run_id, freshness: receipt.freshness_state ?? null});
await live.getByText(/landed|uploaded/i).waitFor({timeout: 10000});
await page.waitForFunction(id => document.querySelector(`a[href="/runs/${id}"]`), receipt.run_id);
assert.equal(await href(ar), "/runs/" + receipt.run_id);
assert.equal(requests.length, 1);
assert.equal(new URL(requests[0]).pathname, "/sources/" + encodeURIComponent(aid) + "/upload");
} else {
let filename = mode === "RP2-xlsx" ? "unique.xlsx" : mode === "RP2-json" ? "unique.json" : mode === "RP3" ? "invalid.csv" : mode + ".csv";
if (mode === "RP4") filename = "duplicate.csv";
if (mode === "RP5" || mode === "RP5-old-ready") {
const reverse = mode === "RP5-old-ready";
let releaseOld;
let oldSeen;
let oldDone;
const gate = new Promise(resolve => { releaseOld = resolve; });
const seen = new Promise(resolve => { oldSeen = resolve; });
const settled = new Promise(resolve => { oldDone = resolve; });
let oldState = "pending";
let oldError = null;
let first = true;
await page.route("**/sources/**/dry-run", async route => {
if (!first) { await route.continue(); return; }
first = false;
oldSeen();
try {
const real = await route.fetch();
await gate;
await route.fulfill({response: real});
oldState = "delivered";
} catch (error) {
const failure = route.request().failure();
if (failure && /abort|cancel/i.test(failure.errorText)) oldState = "cancelled";
else { oldState = "error"; oldError = String(error); }
} finally { oldDone(); }
});
await ar.locator('input[type="file"]').setInputFiles(work + (reverse ? "/RP5.csv" : "/invalid.csv"));
await seen;
const latestName = reverse ? "invalid.csv" : "RP5.csv";
const latestResponse = page.waitForResponse(response => response.url().includes("/sources/") && response.url().endsWith("/dry-run") && (response.request().postData() || "").includes(latestName));
await ar.locator('input[type="file"]').setInputFiles(work + "/" + latestName);
const latest = await latestResponse;
assert.equal(latest.status(), 200);
const preview = await latest.json();
assert.equal(preview.ready, !reverse);
assert.equal(preview.target.source_asset_id, aid);
assert.equal(preview.target.upload_path, "/upload/configured-csv");
releaseOld();
await settled;
await page.waitForLoadState("networkidle");
step("stale-preflight", {oldState, oldError, latestName, ready: preview.ready});
assert.ok(["delivered", "cancelled"].includes(oldState));
assert.equal(await ar.locator('input[type="file"]').evaluate(input => input.files[0].name), latestName);
if (reverse) assert.ok(await named.isDisabled());
else {
assert.ok(await named.isEnabled());
await assertVisiblePreview(page, ar, aName, latestName, preview);
}
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
const preview = await prepare(page, mode === "RP4" ? bName : mode === "RP-stale" ? cName : aName, filename);
if (!["RP3", "RP-wrong-id", "RP-wrong-path"].includes(mode)) {
const previewTarget = mode === "RP4" ? br : mode === "RP-stale" ? cr : ar;
const previewName = mode === "RP4" ? bName : mode === "RP-stale" ? cName : aName;
const previewId = mode === "RP4" ? bid : mode === "RP-stale" ? "bank_partner_overdue" : aid;
assert.equal(preview.target.source_asset_id, previewId);
assert.equal(preview.target.upload_path, "/upload/configured-csv");
if (mode === "RP1") assert.equal(preview.row_count, 3);
await assertVisiblePreview(page, previewTarget, previewName, filename, preview);
}
if (mode.startsWith("RP-wrong-")) {
assert.equal(faults, 1);
await page.waitForTimeout(300);
assert.ok(await named.count() === 0 || await named.isDisabled());
assert.equal(requests.length, 0);
}
}
if (mode.startsWith("RP-wrong-") || mode === "RP5-old-ready") {
assert.equal(requests.length, 0);
} else if (mode === "RP3") {
assert.ok(await named.isDisabled());
assert.match(await ar.innerText(), /issue|required|invalid/i);
assert.equal(requests.length, 0);
} else {
const target = mode === "RP4" ? br : mode === "RP-stale" ? cr : ar;
const targetName = mode === "RP4" ? bName : mode === "RP-stale" ? cName : aName;
const button = target.getByRole("button", {name: "Upload to " + targetName});
await button.waitFor({state: "visible"});
if (mode === "RP6") await page.route("**/sources/**/upload", async route => {await new Promise(resolve => setTimeout(resolve, 800)); await route.continue();});
const receiptPromise = page.waitForResponse(r => r.url().endsWith("/upload") && r.request().method() === "POST");
if (mode === "RP6") await button.dblclick();
else await button.click();
const receipt = await (await receiptPromise).json();
assert.equal(typeof receipt.run_id, "string");
assert.ok(receipt.run_id.length > 0 && receipt.run_id.length <= 256);
step("receipt", {runId: receipt.run_id, freshness: receipt.freshness_state ?? null});
await page.waitForFunction(id => document.querySelector(`a[href="/runs/${id}"]`), receipt.run_id);
assert.equal(await href(target), "/runs/" + receipt.run_id);
await page.waitForTimeout(500);
assert.equal(requests.length, 1);
const selectedId = mode === "RP4" ? bid : mode === "RP-stale" ? "bank_partner_overdue" : aid;
assert.equal(new URL(requests[0]).pathname, "/sources/" + encodeURIComponent(selectedId) + "/upload");
assert.equal(new URL(page.url()).pathname, "/sources");
assert.equal(await page.evaluate(() => window.__hla1587_marker), "same-page");
const text = await target.innerText();
if (mode === "RP-stale") {
const labels = {current: /current|fresh/i, overdue: /overdue|stale/i, due_soon: /due.?soon|expected/i, missing_period: /missing/i, parse_failed: /failed|rejected/i};
assert.ok(labels[receipt.freshness_state], "unrecognized observed freshness");
assert.match(text, labels[receipt.freshness_state]);
}
if (mode === "RP4") assert.match(text, /duplicate|already/i);
else {
assert.match(text, /landed|uploaded/i);
if (mode === "RP-stale") assert.equal(await href(ar), beforeA);
else assert.notEqual(await href(ar), beforeA);
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


def _land_historical_overdue(client):
    content = CSV.replace(b"Electric Utility", b"Page historical overdue baseline")
    result = _multipart(client, "/ingest/configured-csv", C, "historical.csv", content)
    assert result.status_code == 201, result.text
    identifier = result.json()["run"]["run_id"]
    _detail(client, identifier, C)
    # Only this owned synthetic run is aged; the real receipt and manifest
    # retain source identity, and freshness reads the run metadata timestamp.
    with sqlite3.connect(client._hla_fixture_data / "config.db") as connection:
        previous = connection.execute("SELECT created_at, status FROM ingestion_runs WHERE run_id = ?", (identifier,)).fetchone()
        assert previous is not None and previous[1] == "landed"
        changed = connection.execute("UPDATE ingestion_runs SET created_at = ? WHERE run_id = ? AND status = ?", ("2020-01-01T00:00:00+00:00", identifier, "landed"))
        assert changed.rowcount == 1
        connection.commit()
    stale = _rows(client)[C]
    _trace("fixture", {"aged_run_id": identifier, "original_timestamp": previous[0], "observed_row": stale})
    assert stale["latest_run_id"] == identifier and stale["freshness_state"] == "overdue", stale
    assert stale["landed_at"].startswith("2020-01-01")
    _detail(client, identifier, C)
    return identifier


def test_loaded_overdue_fixture_and_receipt(isolated_api):
    client, _ = isolated_api
    before = _rows(client)
    old = _land_historical_overdue(client)
    assert _rows(client)[C]["latest_run_id"] == old
    result = _multipart(client, "/ingest/configured-csv", C, "RP-stale.csv", _success_bytes("RP-stale"))
    assert result.status_code == 201, result.text
    identifier = result.json()["run"]["run_id"]
    assert identifier != old
    _detail(client, identifier, C)
    after = _rows(client)
    assert after[C]["latest_run_id"] == identifier
    assert after[A] == before[A] and after[B] == before[B]


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
    run_ids.append(_land_historical_overdue(client))
    (work / "browser.cjs").write_text(BROWSER_SCRIPT)
    (work / "normal.csv").write_bytes(CSV.replace(b"Electric Utility", b"Ordinary browser upload"))
    (work / "aria.csv").write_bytes(CSV.replace(b"Electric Utility", b"Aria announcement upload"))
    for case in ("RP1", "RP5", "RP6", "RP-stale", "RP-wrong-id", "RP-wrong-path"):
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


def _container_state(name, env):
    result = subprocess.run(["docker", "ps", "-a", "--no-trunc", "--filter", "name=^/" + name + "$", "--format", "{{.ID}}"], env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    identifiers = result.stdout.split()
    assert len(identifiers) <= 1
    if not identifiers:
        return None
    identifier = identifiers[0]
    assert re.fullmatch(r"[0-9a-f]{64}", identifier)
    detail = subprocess.run(["docker", "inspect", "--format", '{{.Id}} {{.State.Running}} {{index .Config.Labels "hla.acceptance"}}', identifier], env=env, capture_output=True, text=True, timeout=15)
    assert detail.returncode == 0, detail.stderr
    fields = detail.stdout.split()
    assert len(fields) == 3 and fields[0] == identifier and fields[2] == name, detail.stdout
    return identifier, fields[1] == "true"


def _cleanup_container(name, env, evidence, expected_id=None):
    observed = []
    mismatches = []
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        state = _container_state(name, env)
        if state is not None:
            identifier, running = state
            if expected_id is not None and identifier != expected_id:
                mismatches.append((identifier, expected_id))
            removed = subprocess.run(["docker", "rm", "-f", identifier], env=env, capture_output=True, text=True, timeout=30)
            observed.append({"id": identifier, "was_running": running, "exit": removed.returncode, "stdout": removed.stdout, "stderr": removed.stderr})
            assert removed.returncode == 0, removed.stderr
        time.sleep(0.1)
    assert _container_state(name, env) is None
    with evidence.open("a") as stream:
        stream.write("\nCONTAINER_CLEANUP " + json.dumps(observed) + "\n")
    assert not mismatches, mismatches


def _run_browser(command, env, log, *, native, force_failure=False, container_name=None):
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
                if native:
                    os.killpg(int(pids[-1]), signal.SIGSTOP)
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
                    os.killpg(int(pids[-1]), 0)
                    _trace("guard", {"node_killed": process.pid, "browser_alive": int(pids[-1])})
                else:
                    before = _container_state(container_name, env)
                    assert before is not None and before[1], before
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
                    after = _container_state(container_name, env)
                    assert after == before and after[1], (before, after)
                    output.write(("GUARD_CONTAINER_ID=" + after[0] + "\n").encode())
                    output.flush()
                    _trace("guard", {"client_killed": process.pid, "container_alive": after[0], "label": container_name, "browser_pid_in_container": int(pids[-1])})
                raise RuntimeError("forced browser owner failure")
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


def _assert_receipt_id(receipt_id, actual_id):
    assert isinstance(receipt_id, str) and 0 < len(receipt_id) <= 256
    assert receipt_id == actual_id


def test_receipt_id_guard_rejects_fabrication():
    _assert_receipt_id("actual-run", "actual-run")
    with pytest.raises(AssertionError) as mismatch:
        _assert_receipt_id("fabricated-run", "actual-run")
    _trace("guard", {"receipt_id_mismatch": str(mismatch.value), "bff": "fabricated-run", "actual": "actual-run"})


def _browser_case(real_page, case):
    base, work, run_ids, client = real_page
    before = _population(client)
    before_rows = _rows(client)
    if case == "RP-stale":
        assert before_rows[C]["freshness_state"] == "overdue"
        assert before_rows[C]["latest_run_id"] == run_ids[2]
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
    native = probe_exit == 0 and not os.environ.get("HLA_FORCE_BROWSER_FALLBACK")
    if os.environ.get("HLA_ASSERT_DOCKER_ONLY"):
        assert not native and probe_exit != 0
        assert not Path(env["PLAYWRIGHT_BROWSERS_PATH"]).exists()
        assert "LD_LIBRARY_PATH" not in env
    env.update(WEB_BASE=base, CASE_ID=case, RUN_A=run_ids[0], RUN_B=run_ids[1], RUN_C=run_ids[2])
    if native:
        env["WORK_DIR"] = str(work)
        command = ["node", str(work / "browser.cjs")]
    else:
        command = ["docker", "run", "--pull=never", "--name", name, "--label", "hla.acceptance=" + name, "--network", "host", "-v", str(work) + ":/work:ro", "-e", "WORK_DIR=/work", "-e", "WEB_BASE=" + base, "-e", "CASE_ID=" + case, "-e", "RUN_A=" + run_ids[0], "-e", "RUN_B=" + run_ids[1], "-e", "RUN_C=" + run_ids[2], "sha256:b0ab6f3cb99aa7803adbc14d9027ec1785fc6e433b97e134e0f8fe61683b6b53", "node", "/work/browser.cjs"]
    evidence = work / ("browser-" + case + "-" + name + ".log")
    _trace("fixture", {"browser_topology": "native" if native else "docker", "native_probe_exit": probe_exit, "browser_cache": env["PLAYWRIGHT_BROWSERS_PATH"], "browser_cache_exists": Path(env["PLAYWRIGHT_BROWSERS_PATH"]).exists(), "ld_library_path_present": "LD_LIBRARY_PATH" in env})
    try:
        exit_code = _run_browser(command, env, evidence, native=native, force_failure=case == "guard-browser-failure", container_name=name if not native else None)
        output = evidence.read_text(errors="replace")
        assert exit_code == 0, output
        lines = [line.removeprefix("RESULT ") for line in output.splitlines() if line.startswith("RESULT ")]
        assert len(lines) == 1, output
        browser_result = json.loads(lines[0])
        assert browser_result["case"] == case
        after = _population(client)
        if case in ("RP1", "RP2-xlsx", "RP2-json", "RP4", "RP5", "RP6", "RP10", "RP-stale"):
            new = after - before
            assert len(new) == 1, (case, before, after)
            target = B if case == "RP4" else C if case == "RP-stale" else A
            steps = [step["data"] for step in browser_result["steps"] if step["name"] == "receipt"]
            assert len(steps) == 1
            actual_id = next(iter(new))
            _assert_receipt_id(steps[0]["runId"], actual_id)
            run = _detail(client, actual_id, target)
            if case == "RP5":
                assert run["sha256"] == hashlib.sha256(_success_bytes("RP5")).hexdigest()
            if case == "RP4":
                assert run["status"] == "rejected"
            else:
                assert run["status"] == "landed"
            after_rows = _rows(client)
            if case == "RP-stale":
                assert steps[0]["freshness"] == after_rows[C]["freshness_state"]
            siblings = (A, B) if target == C else (A,) if target == B else (B,)
            for sibling in siblings:
                assert after_rows[sibling] == before_rows[sibling]
            assert after_rows[target]["latest_run_id"] == next(iter(new))
        if case in ("RP3", "RP7", "RP-nojs", "RP-wrong-id", "RP-wrong-path", "RP5-old-ready", "guard-fault-rewrite", "guard-nojs-external-form", "guard-visible-preview"):
            assert after == before, (case, before, after)
    finally:
        if not native:
            ids = re.findall(r"^GUARD_CONTAINER_ID=([0-9a-f]{64})$", evidence.read_text(errors="replace"), re.MULTILINE)
            try:
                assert len(ids) <= 1
            finally:
                _cleanup_container(name, env, evidence, expected_id=ids[0] if len(ids) == 1 else None)


def test_visible_preview_facts_guard(real_page):
    _browser_case(real_page, "guard-visible-preview")


def test_nojs_external_form_fault_is_detected(real_page):
    _browser_case(real_page, "guard-nojs-external-form")


def test_real_preflight_fault_rewrite_is_closed(real_page):
    _browser_case(real_page, "guard-fault-rewrite")


def test_rp8_rp9_and_page_positive_controls(real_page):
    _browser_case(real_page, "positive")


@pytest.mark.parametrize("case", ["RP1", "RP2-xlsx", "RP2-json", "RP3", "RP4", "RP5", "RP6", "RP7", "RP10", "RP-nojs", "RP-wrong-id", "RP-wrong-path", "RP-stale", "RP5-old-ready"])
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
    assert payload["message"] == "Upload outcome could not be confirmed."
    observation_keys = {"observed_latest_run_id", "observation", "freshness_state"}
    supplied = observation_keys.intersection(payload)
    if supplied:
        assert supplied == observation_keys
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


def test_build_cleanup_handles_exited_leader_and_ignoring_child(tmp_path):
    ready = tmp_path / "build-child-ready"
    child = """
import pathlib, signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
pathlib.Path(sys.argv[1]).write_text("ready")
time.sleep(60)
"""
    leader = """
import pathlib, subprocess, sys, time
subprocess.Popen([sys.executable, "-c", sys.argv[1], sys.argv[2]])
while not pathlib.Path(sys.argv[2]).exists():
    time.sleep(0.05)
print("leader-exiting", flush=True)
sys.exit(7)
"""
    result = _run_build("forced-build", [sys.executable, "-c", leader, child, str(ready)], tmp_path, _environment(tmp_path / "env", _port()), tmp_path, timeout=15)
    record = json.loads((tmp_path / "forced-build.ownership.json").read_text())
    assert result == 7 and record["inner_exit"] == 7
    assert record["group_alive_after_leader"] and record["group_absent"]
    assert "leader-exiting" in (tmp_path / "forced-build.log").read_text()
    _assert_group_gone(record["pgid"])


def test_selected_browser_failure_finalizer_stops_group(real_page):
    _, work, _, _ = real_page
    prior = set(work.glob("browser-guard-browser-failure-*.log"))
    with pytest.raises(RuntimeError, match="forced browser owner failure"):
        _browser_case(real_page, "guard-browser-failure")
    created = set(work.glob("browser-guard-browser-failure-*.log")) - prior
    assert len(created) == 1
    evidence = created.pop()
    text = evidence.read_text(errors="replace")
    name = evidence.name.removeprefix("browser-guard-browser-failure-").removesuffix(".log")
    env = _environment(work / ("browser-env-" + name), _port())
    cleanup = re.search(r"^CONTAINER_CLEANUP (\[.*\])$", text, re.MULTILINE)
    if "COMMAND ['docker'," in text:
        try:
            assert cleanup is not None
            observed = json.loads(cleanup.group(1))
            assert len(observed) == 1 and observed[0]["exit"] == 0
            identifier = observed[0]["id"]
            guard_ids = re.findall(r"^GUARD_CONTAINER_ID=([0-9a-f]{64})$", text, re.MULTILINE)
            assert guard_ids == [identifier]
            assert _container_state(name, env) is None
            result = subprocess.run(["docker", "ps", "-a", "--no-trunc", "--filter", "id=" + identifier, "--format", "{{.ID}}"], env=env, capture_output=True, text=True, timeout=15)
            assert result.returncode == 0 and not result.stdout.strip(), result.stderr + result.stdout
            _trace("guard", {"post_return_container_absent": identifier})
        except BaseException:
            _cleanup_container(name, env, evidence)
            raise
    else:
        try:
            pids = re.findall(r"^OWNED_BROWSER_PID=(\d+)$", text, re.MULTILINE)
            assert pids
            _assert_group_gone(int(pids[-1]))
            _trace("guard", {"post_return_browser_group_absent": int(pids[-1])})
        except BaseException:
            _stop_browser_groups(evidence, env["TMPDIR"])
            raise



def test_cleanup_noop_is_falsified(real_page, monkeypatch):
    seen = []
    original_native = _stop_browser_groups
    original_docker = _cleanup_container

    def native_once(log, profile):
        if log.name.startswith("browser-guard-browser-failure-") and not seen:
            seen.append("native")
            return
        return original_native(log, profile)

    def docker_once(name, env, evidence, expected_id=None):
        if evidence.name.startswith("browser-guard-browser-failure-") and not seen:
            seen.append("docker")
            return
        return original_docker(name, env, evidence, expected_id)

    monkeypatch.setitem(globals(), "_stop_browser_groups", native_once)
    monkeypatch.setitem(globals(), "_cleanup_container", docker_once)
    with pytest.raises((AssertionError, RuntimeError)):
        test_selected_browser_failure_finalizer_stops_group(real_page)
    assert seen in (["native"], ["docker"])
    _trace("guard", {"noop_cleanup_detected": seen[0]})


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
    "test_visible_preview_facts_guard",
    "test_nojs_external_form_fault_is_detected",
    "test_cleanup_noop_is_falsified",
    "test_rejected_receipt_context_guard_rejects_false_identity",
    "test_receipt_id_guard_rejects_fabrication",
    "test_loaded_overdue_fixture_and_receipt",
    "test_rejected_receipt_requires_actual_source_context[match-400]",
    "test_rejected_receipt_requires_actual_source_context[match-409]",
    "test_rejected_receipt_requires_actual_source_context[contradiction-400]",
    "test_rejected_receipt_requires_actual_source_context[contradiction-409]",
    "test_rejected_receipt_requires_actual_source_context[forbidden-400]",
    "test_rejected_receipt_requires_actual_source_context[forbidden-409]",
    "test_rejected_receipt_requires_actual_source_context[reset-400]",
    "test_rejected_receipt_requires_actual_source_context[reset-409]",
    "test_build_cleanup_handles_exited_leader_and_ignoring_child",
    "test_rp_inline_feature[RP-stale]",
    "test_rp_inline_feature[RP5-old-ready]",
    "test_receiptless_status_guard_rejects_false_certainty",
    "test_real_preflight_fault_rewrite_is_closed",
    'test_observation_guard_rejects_ignored_freshness',
    'test_response_guard_rejects_raw_spread',
    'test_cleanup_kills_surviving_child_after_leader_exit',
    'test_selected_browser_failure_finalizer_stops_group',
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
