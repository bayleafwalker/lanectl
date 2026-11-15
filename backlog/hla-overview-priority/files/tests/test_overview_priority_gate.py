"""Source-bound entrypoint for the independent overview priority acceptance."""

from __future__ import annotations

import hashlib
import os
import platform
import runpy
import shlex
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

NODE_URL = "https://nodejs.org/dist/v20.20.1/node-v20.20.1-linux-x64.tar.xz"
NODE_SHA256 = "1592ef30f7a63309581a130f7fd8b3311a3e08ee0c609a3d13234590fe35409f"
RUNNER_SHA256 = '55731cc4411d203755e6b68f73e655cf95782e28cf4569a9e928c0c1a7f73801'
TEST_SHA256 = 'bffa379ba2823106620572f52deac584aa7ee0711d20054f107e27b8ed93dcae'

RUNNER_SOURCE = r'''#!/usr/bin/env python3
"""Private, source-bound bootstrap. Exit 2 means infrastructure, 1 semantic red."""
import argparse
import ctypes
import hashlib
import json
import os
import pathlib
import re
import signal
import subprocess
import sys
import tarfile
import time
from types import SimpleNamespace

HERE = pathlib.Path(__file__).resolve().parent
EXPECTED_CASES = ['test_assistant_evidence_prioritizes_same_real_rows', 'test_assistant_headline_and_evidence_use_same_priority', 'test_briefing_known_severity_conventions', 'test_briefing_unknown_and_tie_order', 'test_briefing_unknown_only_is_neutral', 'test_browser_history_complete_order', 'test_browser_history_unrecognized_is_visible_and_neutral', 'test_browser_owner_failure_cleans_exact_group', 'test_browser_positive_real_page_population[first-6]', 'test_browser_positive_real_page_population[home-9]', 'test_browser_positive_real_page_population[ingest-5]', 'test_browser_positive_real_page_population[operating-8]', 'test_browser_priority_and_labels[first-6]', 'test_browser_priority_and_labels[home-9]', 'test_browser_priority_and_labels[ingest-5]', 'test_browser_priority_and_labels[operating-8]', 'test_console_recognized_and_unknown_labels', 'test_console_unknown_order_and_labels', 'test_consumers_real_api_population_and_restore', 'test_current_priority_and_tie_identity[prefer-fallback]', 'test_current_priority_and_tie_identity[prefer-present]', 'test_current_priority_and_tie_identity[published]', 'test_current_priority_and_tie_identity[warehouse]', 'test_duplicate_rows_preserved_real_http[prefer-fallback]', 'test_duplicate_rows_preserved_real_http[prefer-present]', 'test_duplicate_rows_preserved_real_http[published]', 'test_duplicate_rows_preserved_real_http[warehouse]', 'test_exited_leader_ignoring_child_is_cleaned', 'test_historical_priority_and_snapshot_immutable[prefer-fallback]', 'test_historical_priority_and_snapshot_immutable[prefer-present]', 'test_historical_priority_and_snapshot_immutable[published]', 'test_historical_priority_and_snapshot_immutable[warehouse]', 'test_infrastructure_guards_reject_unavailable_hash_and_noop', 'test_no_history_is_empty_and_not_current[prefer-fallback]', 'test_no_history_is_empty_and_not_current[prefer-present]', 'test_no_history_is_empty_and_not_current[published]', 'test_no_history_is_empty_and_not_current[warehouse]', 'test_oidc_publication_permission', 'test_positive_auth_and_current_population[prefer-fallback]', 'test_positive_auth_and_current_population[prefer-present]', 'test_positive_auth_and_current_population[published]', 'test_positive_auth_and_current_population[warehouse]', 'test_priority_oracle_rejects_inversion', 'test_reversed_tie_insertion_real_http[published]', 'test_reversed_tie_insertion_real_http[warehouse]', 'test_review_recognized_warning_and_unknown_neutral', 'test_review_unknown_and_tie_order', 'test_snapshot_read_preserves_saved_bytes[published]', 'test_snapshot_read_preserves_saved_bytes[warehouse]', 'test_source_value_guard_rejects_tampering', 'test_wallboard_recognized_warning_threshold[2]', 'test_wallboard_recognized_warning_threshold[3]', 'test_wallboard_unknown_does_not_warn']


def run(name, command, cwd, env, output):
    stdout = output / (name + ".stdout")
    stderr = output / (name + ".stderr")
    libc = ctypes.CDLL(None)
    prior = ctypes.c_int()
    if libc.prctl(37, ctypes.byref(prior), 0, 0, 0) or libc.prctl(36, 1, 0, 0, 0):
        raise RuntimeError("cannot establish subreaper")
    timeout = False
    process = None
    absent = False
    launch_error = None
    try:
        with stdout.open("wb") as out, stderr.open("wb") as err:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=out, stderr=err, start_new_session=True)
            try:
                process.wait(timeout=900)
            except subprocess.TimeoutExpired:
                timeout = True
    except OSError as error:
        launch_error = repr(error)
    finally:
        try:
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    absent = True
                deadline = time.monotonic() + 2
                killed = False
                while not absent and time.monotonic() < deadline + 10:
                    process.poll()
                    try:
                        while os.waitpid(-process.pid, os.WNOHANG)[0]:
                            pass
                    except ChildProcessError:
                        pass
                    try:
                        os.killpg(process.pid, 0)
                    except ProcessLookupError:
                        absent = True
                        break
                    if not killed and time.monotonic() >= deadline:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            absent = True
                        killed = True
                    time.sleep(.05)
                process.wait(timeout=10)
        finally:
            if libc.prctl(36, prior.value, 0, 0, 0):
                raise RuntimeError("cannot restore subreaper")
    record = {"command": command, "exit": process.returncode if process else None, "timeout": timeout, "group_absent": absent, "launch_error": launch_error}
    (output / (name + ".json")).write_text(json.dumps(record) + "\n")
    if launch_error or timeout or not absent:
        raise RuntimeError(name + " launch, deadline or cleanup failure")
    return SimpleNamespace(returncode=process.returncode, stdout=stdout.read_text(), stderr=stderr.read_text())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--checkout', required=True, type=pathlib.Path)
    parser.add_argument('--output', required=True, type=pathlib.Path)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--node', required=True, type=pathlib.Path)
    parser.add_argument('--python', required=True, type=pathlib.Path)
    parser.add_argument('--browser-cache', required=True, type=pathlib.Path)
    parser.add_argument('--test-sha256', required=True)
    args = parser.parse_args()
    test = HERE / 'test_overview_priority_acceptance.py'
    if hashlib.sha256(test.read_bytes()).hexdigest() != args.test_sha256:
        raise RuntimeError('bound test hash mismatch')
    source = args.checkout.resolve()
    output = args.output.resolve()
    if output.exists():
        raise RuntimeError('output must not exist')
    if output == source or source in output.parents:
        raise RuntimeError('output must be outside checkout')
    head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if head != args.commit or subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain', '--untracked-files=no'], text=True):
        raise RuntimeError('stale source or dirty tracked files')
    if not args.python.is_file():
        raise RuntimeError('Python unavailable')
    if not args.node.is_file():
        raise RuntimeError('node unavailable')
    version = subprocess.check_output([str(args.node), '--version'], text=True).strip()
    if not version.startswith('v20.'):
        raise RuntimeError('Node 20 required')
    output.mkdir(parents=True)
    frozen_test = output / 'test_overview_priority_acceptance.py'
    frozen_test.write_bytes(test.read_bytes())
    if hashlib.sha256(frozen_test.read_bytes()).hexdigest() != args.test_sha256:
        raise RuntimeError('test changed during binding')
    for d in ('home', 'tmp', 'cache'):
        (output / d).mkdir()
    env = {'HOME': str(output / 'home'), 'XDG_CACHE_HOME': str(output / 'cache'),
           'TMPDIR': str(output / 'tmp'), 'PATH': str(args.node.resolve().parent) + os.pathsep + os.environ.get('PATH', os.defpath),
           'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1', 'UV_CACHE_DIR': str(output / 'cache/uv'),
           'npm_config_cache': str(output / 'cache/npm'), 'NEXT_TELEMETRY_DISABLED': '1',
           'PLAYWRIGHT_BROWSERS_PATH': str(args.browser_cache.resolve())}
    for key in ('LD_LIBRARY_PATH', 'FONTCONFIG_FILE', 'FONTCONFIG_PATH', 'SSL_CERT_FILE'):
        if os.environ.get(key):
            env[key] = os.environ[key]
    archive = output / 'source.tar'
    with archive.open('wb') as file:
        process = subprocess.run(['git', '-C', str(source), 'archive', head], stdout=file, stderr=subprocess.PIPE)
    (output / 'archive.json').write_text(json.dumps({'exit': process.returncode, 'commit': head}) + '\n')
    if process.returncode:
        raise RuntimeError('source archive failed')
    target = output / 'checkout'
    target.mkdir()
    with tarfile.open(archive) as tar:
        tar.extractall(target, filter='data')
    archive.unlink()
    env.update(HLA_ACCEPTANCE_OUTPUT=str(output), HLA_ACCEPTANCE_CHECKOUT=str(target), HLA_ACCEPTANCE_NODE=str(args.node.resolve()), PYTHONPATH=str(target))
    for name, command, cwd in [
        ('uv-sync', ['uv', 'sync', '--frozen', '--extra', 'dev', '--python', str(args.python.resolve())], target),
        ('npm-ci', ['npm', 'ci', '--no-audit', '--no-fund'], target / 'apps/web/frontend'),
        ('next-build', ['npm', 'run', 'build'], target / 'apps/web/frontend'),
    ]:
        result = run(name, command, cwd, env, output)
        if result.returncode:
            raise RuntimeError(name + ' failed; see recorded output')
    (output / 'binding.json').write_text(json.dumps({'source_commit': head, 'test_sha256': hashlib.sha256(test.read_bytes()).hexdigest()}) + '\n')
    result = run('pytest', [str(target / '.venv/bin/python'), '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '--basetemp=' + str(output / 'pytest-tmp'), '--junitxml=' + str(output / 'junit.xml'), str(frozen_test)], output, env, output)
    if not (output / 'junit.xml').exists():
        raise RuntimeError('pytest did not produce JUnit')
    code = """import json,sys,xml.etree.ElementTree as ET
cases=ET.parse(sys.argv[1]).findall('.//testcase')
print(json.dumps([{'name':c.attrib['name'],'failure':c.find('failure') is not None,'failure_message':c.find('failure').get('message') if c.find('failure') is not None else None,'failure_type':c.find('failure').get('type') if c.find('failure') is not None else None,'phase':'call' if c.find('failure') is not None else ('setup_or_teardown' if c.find('error') is not None else 'passed_or_skipped'),'error':c.find('error') is not None,'error_message':c.find('error').get('message') if c.find('error') is not None else None,'skipped':c.find('skipped') is not None} for c in cases]))
"""
    parsed = run('population', [str(target / '.venv/bin/python'), '-c', code, str(output / 'junit.xml')], output, env, output)
    if parsed.returncode:
        raise RuntimeError('cannot parse JUnit')
    cases = json.loads(parsed.stdout)
    semantic_categories = {
        "test_current_priority_and_tie_identity": {"ordering"},
        "test_historical_priority_and_snapshot_immutable": {"ordering"},
        "test_reversed_tie_insertion_real_http": {"tie-order"},
        "test_assistant_evidence_prioritizes_same_real_rows": {"assistant-order"},
        "test_browser_priority_and_labels": {"browser-order", "browser-label"},
        "test_browser_history_unrecognized_is_visible_and_neutral": {"unknown-label"},
        "test_review_unknown_and_tie_order": {"consumer-order"},
        "test_review_recognized_warning_and_unknown_neutral": {"review-label"},
        "test_console_recognized_and_unknown_labels": {"console-label"},
        "test_console_unknown_order_and_labels": {"consumer-order", "console-label"},
        "test_wallboard_unknown_does_not_warn": {"wallboard-unknown"},
        "test_briefing_unknown_and_tie_order": {"briefing-order"},
        "test_assistant_headline_and_evidence_use_same_priority": {"assistant-headline", "assistant-order"},
        "test_browser_history_complete_order": {"history-order"},
    }
    for case in cases:
        case["classification"] = "passed"
        if case["error"] or case["skipped"]:
            case["classification"] = "infrastructure"
        elif case["failure"]:
            match = re.fullmatch(r"(?:[A-Za-z_][A-Za-z_0-9.]*\.)?SemanticPriorityFailure: HLA_SEMANTIC_PRIORITY:([a-z-]+)", case["failure_message"] or "")
            base = case["name"].split("[", 1)[0]
            case["classification"] = "semantic" if match and match.group(1) in semantic_categories.get(base, set()) else "infrastructure"
    (output / "classified-population.json").write_text(json.dumps(cases, indent=2) + "\n")
    if sorted(c["name"] for c in cases) != EXPECTED_CASES or any(c["classification"] == "infrastructure" for c in cases):
        raise RuntimeError("incomplete population or unclassified/control failure")
    if hashlib.sha256(frozen_test.read_bytes()).hexdigest() != args.test_sha256:
        raise RuntimeError('bound test changed during run')
    return result.returncode


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        print('INFRASTRUCTURE:', type(error).__name__, str(error), file=sys.stderr)
        sys.exit(2)
'''

TEST_SOURCE = r'''"""Independent real-PostgreSQL/HTTP/Next priority acceptance draft for HLA overview.

Base qualification expects semantic failures: this file does not implement the fix.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

import httpx
import psycopg
import pytest
import uvicorn
from apps.api.app import create_app
from packages.domains.finance.pipelines.account_transaction_service import (
    AccountTransactionService,
)
from packages.domains.overview.pipelines.transformation_overview import (
    refresh_open_attention_items,
)
from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
from packages.pipelines.reporting_snapshots import (
    PublicationSnapshot,
    PublicationSnapshotStore,
)
from packages.pipelines.transformation_service import TransformationService
from packages.platform.auth.crypto import hash_password
from packages.platform.auth.session_manager import SessionManager
from packages.shared.auth import build_oidc_provider, build_session_manager
from packages.shared.settings import AppSettings
from packages.storage.auth_store import LocalUserCreate, UserRole
from packages.storage.duckdb_store import DuckDBStore
from packages.storage.ingestion_config import IngestionConfigRepository
from packages.storage.postgres_reporting import PostgresReportingStore
from packages.storage.run_metadata import RunMetadataRepository
from tests.oidc_test_support import MockOidcIssuer

ROOT = Path(os.environ["HLA_ACCEPTANCE_OUTPUT"]).resolve()
BASE = Path(os.environ["HLA_ACCEPTANCE_CHECKOUT"]).resolve()
RUN = ROOT / "run"
RUN.mkdir(parents=True, exist_ok=True)
FRONTEND = BASE / "apps/web/frontend"
NODE = os.environ["HLA_ACCEPTANCE_NODE"]
IMAGE = "postgres@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea"
PASSWORD = "synthetic-local-password"


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def trace(stage, **fields):
    with (RUN / "acceptance.trace.jsonl").open("a") as stream:
        print(
            json.dumps({"stage": stage, **fields}, default=str), file=stream, flush=True
        )


def stop_pid_group(pid, process=None):
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
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
            trace("group_absent", pid=pid)
            return
        if time.monotonic() >= deadline and not killed:
            os.killpg(pid, signal.SIGKILL)
            killed = True
        time.sleep(0.05)
    raise RuntimeError(f"owned process group {pid} survived cleanup")


def stop_group(process):
    stop_pid_group(process.pid, process)


def stop_browser_groups(log, profile):
    owned = str(profile).encode()
    groups = {
        int(value)
        for value in re.findall(
            r"^BROWSER_PID=(\d+)$", log.read_text(errors="replace"), re.MULTILINE
        )
    }
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            if (
                int(stat[1]) == os.getpid()
                and owned in (entry / "cmdline").read_bytes()
            ):
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
            trace("browser_group_absent", pid=pid)
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
        stop_pid_group(pid)


def docker_env():
    config = ROOT / "docker-config"
    config.mkdir(exist_ok=True)
    return {
        "PATH": os.environ.get("PATH", os.defpath),
        "DOCKER_HOST": "unix:///var/run/docker.sock",
        "DOCKER_CONFIG": str(config),
    }


def docker(*args):
    result = subprocess.run(
        ["docker", *args], env=docker_env(), capture_output=True, text=True, timeout=60
    )
    trace(
        "docker",
        args=list(args),
        exit=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )
    return result


def make_app(data, ts, reporting, identity="local", issuer=None):
    data.mkdir(parents=True, exist_ok=True)
    repository = IngestionConfigRepository(data / "config.db")
    for role in (UserRole.ADMIN, UserRole.OPERATOR, UserRole.READER):
        repository.create_local_user(
            LocalUserCreate(
                user_id="fixture-" + role.value,
                username="fixture-" + role.value,
                password_hash=hash_password(PASSWORD),
                role=role,
            )
        )
    metadata = RunMetadataRepository(data / "runs.db")
    service = AccountTransactionService(
        landing_root=data / "landing", metadata_repository=metadata
    )
    run = service.ingest_bytes(
        source_bytes=b"booked_at,account_id,counterparty_name,amount,currency,description\n2026-01-01,fixture,Sample,-1,EUR,fixture\n",
        file_name="fixture.csv",
        source_name="synthetic",
    )
    assert run.passed
    opts = {}
    if identity == "oidc":
        settings = AppSettings.from_env(
            {
                "HOMELAB_ANALYTICS_DATA_DIR": str(data),
                "HOMELAB_ANALYTICS_IDENTITY_MODE": "oidc",
                "HOMELAB_ANALYTICS_SESSION_SECRET": "synthetic-session-secret",
                "HOMELAB_ANALYTICS_OIDC_ISSUER_URL": issuer.issuer_url,
                "HOMELAB_ANALYTICS_OIDC_CLIENT_ID": issuer.client_id,
                "HOMELAB_ANALYTICS_OIDC_CLIENT_SECRET": issuer.client_secret,
                "HOMELAB_ANALYTICS_OIDC_REDIRECT_URI": "http://127.0.0.1/auth/callback",
                "HOMELAB_ANALYTICS_OIDC_API_AUDIENCE": issuer.api_audience,
                "HOMELAB_ANALYTICS_OIDC_READER_GROUPS": "readers",
                "HOMELAB_ANALYTICS_OIDC_OPERATOR_GROUPS": "",
                "HOMELAB_ANALYTICS_OIDC_ADMIN_GROUPS": "",
                "HOMELAB_ANALYTICS_OIDC_PERMISSIONS_CLAIM": "hla_permissions",
            }
        )
        opts = {
            "session_manager": build_session_manager(settings),
            "oidc_provider": build_oidc_provider(
                settings, http_client=issuer.http_client()
            ),
        }
    else:
        opts = {"session_manager": SessionManager("synthetic-session-secret")}
    app = create_app(
        service,
        config_repository=repository,
        auth_store=repository,
        identity_mode=identity,
        transformation_service=ts,
        reporting_service=reporting,
        **opts,
    )

    @app.middleware("http")
    async def observe(request, call_next):
        response = await call_next(request)
        trace(
            "api_observation",
            path=request.url.path,
            query=request.url.query,
            status=response.status_code,
        )
        return response

    return app, run.run_id


def seed(ts):
    s = ts.store
    for ident, title in [
        ("a3", "Alpha High"),
        ("b3", "Beta High"),
        ("c3", "Gamma High"),
    ]:
        s.execute(
            "INSERT INTO mart_contract_review_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [ident, title, "electricity", "expired_contract", 3, 1.5, None, "EUR"],
        )
    for ident, title in [
        ("z-tie", "Twin Medium"),
        ("a-tie", "Twin Medium"),
        ("m2", "Other Medium"),
    ]:
        s.execute(
            "INSERT INTO mart_transaction_anomalies_current VALUES (?, CURRENT_DATE, ?, ?, ?, ?, ?)",
            [ident, title, -42, "debit", "unusual", "Synthetic anomaly"],
        )
    for ident, title in [
        ("pay-a", "Alpha Low"),
        ("pay-b", "Beta Low"),
        ("pay-c", "Gamma Low"),
    ]:
        s.execute(
            "INSERT INTO mart_upcoming_fixed_costs_30d VALUES (?, ?, ?, ?, ?, ?, CURRENT_DATE + 2, ?)",
            [ident, title, "Synthetic Co", "monthly", 10, "EUR", "high"],
        )
    assert refresh_open_attention_items(s) == 9
    return s.fetchall_dicts("SELECT * FROM mart_open_attention_items")


def browser_env(data):
    environment = {
        "HOME": str(data),
        "XDG_CACHE_HOME": str(data / "cache"),
        "TMPDIR": str(data / "tmp"),
        "PATH": str(Path(NODE).parent) + os.pathsep + os.environ.get("PATH", os.defpath),
        "LANG": "C.UTF-8",
        "PLAYWRIGHT_BROWSERS_PATH": os.environ["PLAYWRIGHT_BROWSERS_PATH"],
        "NEXT_TELEMETRY_DISABLED": "1",
    }
    for key in ("LD_LIBRARY_PATH", "FONTCONFIG_FILE", "FONTCONFIG_PATH"):
        if os.environ.get(key):
            environment[key] = os.environ[key]
    return environment



@pytest.fixture(scope="session")
def world():
    name = "hla-priority-acceptance-" + uuid.uuid4().hex
    label = "hla.priority.owner=" + name
    servers = []
    next_process = None
    next_log = None
    identifier = None
    try:
        create = docker(
            "create",
            "--name",
            name,
            "--label",
            label,
            "--publish",
            "127.0.0.1::5432",
            "--env",
            "POSTGRES_DB=acceptance",
            "--env",
            "POSTGRES_USER=acceptance",
            "--env",
            "POSTGRES_PASSWORD=local-synthetic-password",
            IMAGE,
        )
        if create.returncode:
            raise RuntimeError("postgres create failed")
        identifier = create.stdout.strip()
        assert len(identifier) == 64
        started = docker("start", identifier)
        if started.returncode:
            raise RuntimeError("postgres start failed")
        result = docker("port", identifier, "5432/tcp")
        if result.returncode:
            raise RuntimeError("postgres port missing")
        port = int(result.stdout.strip().rsplit(":", 1)[1])
        dsn = f"postgresql://acceptance:local-synthetic-password@127.0.0.1:{port}/acceptance"
        for _ in range(100):
            try:
                with psycopg.connect(dsn, connect_timeout=1) as connection:
                    connection.execute("SELECT 1")
                break
            except psycopg.Error:
                time.sleep(0.2)
        else:
            raise RuntimeError("postgres unavailable")
        ts = TransformationService(DuckDBStore.memory())
        rows = seed(ts)
        ts.store.execute(
            "INSERT INTO mart_monthly_cashflow VALUES ('2020-02', 100, 20, 80, 2), ('2020-03', 100, 20, 80, 2)"
        )
        pg = PostgresReportingStore(dsn, schema="published")
        published = ReportingService(
            ts, publication_store=pg, access_mode=ReportingAccessMode.PUBLISHED
        )
        published.publish_publications(["mart_open_attention_items"])
        warehouse = ReportingService(ts, access_mode=ReportingAccessMode.WAREHOUSE)
        history = [
            next(x for x in rows if x["severity"] == 1),
            next(x for x in rows if x["severity"] == 3),
            next(x for x in rows if x["severity"] == 2),
            dict(
                rows[0],
                item_id="unknown-priority",
                title="Unknown Priority Fixture",
                severity=7,
            ),
            {
                k: v
                for k, v in dict(
                    rows[0],
                    item_id="missing-priority",
                    title="Missing Priority Fixture",
                ).items()
                if k != "severity"
            },
        ]
        snapshot = PublicationSnapshot(
            "mart_open_attention_items",
            "2020-02",
            "2020-03-01T00:00:00Z",
            "synthetic-run",
            history,
        )
        PublicationSnapshotStore.for_duckdb(ts.store).write(
            snapshot, retention_months=1200
        )
        PublicationSnapshotStore.for_postgres(pg).write(snapshot, retention_months=1200)
        before = pg.fetchall_dicts("SELECT * FROM reporting_publication_snapshot")
        before_hash = hashlib.sha256(
            json.dumps(before, sort_keys=True, default=str).encode()
        ).hexdigest()
        empty_pg = PostgresReportingStore(dsn, schema="fallback_empty")
        modes = {
            "warehouse": warehouse,
            "published": published,
            "prefer-present": ReportingService(
                ts,
                publication_store=pg,
                access_mode=ReportingAccessMode.PREFER_PUBLISHED,
            ),
            "prefer-fallback": ReportingService(
                ts,
                publication_store=empty_pg,
                access_mode=ReportingAccessMode.PREFER_PUBLISHED,
            ),
        }
        bases = {}
        runs = {}
        for mode, reporting in modes.items():
            app, run_id = make_app(RUN / ("fixture-" + mode), ts, reporting)
            port = free_port()
            server = uvicorn.Server(
                uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
            )
            thread = threading.Thread(target=server.run)
            thread.start()
            servers.append((server, thread, port))
            for _ in range(200):
                if server.started:
                    break
                if not thread.is_alive():
                    raise RuntimeError("API exited before health")
                time.sleep(0.05)
            else:
                raise RuntimeError("API startup deadline")
            base = f"http://127.0.0.1:{port}"
            health = httpx.get(base + "/health", trust_env=False, timeout=5)
            trace("health", mode=mode, status=health.status_code)
            if health.status_code != 200:
                raise RuntimeError("API health status")
            bases[mode] = base
            runs[mode] = run_id
        issuer = MockOidcIssuer()
        app, _ = make_app(
            RUN / "fixture-oidc", ts, published, identity="oidc", issuer=issuer
        )
        port = free_port()
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        )
        thread = threading.Thread(target=server.run)
        thread.start()
        servers.append((server, thread, port))
        for _ in range(200):
            if server.started:
                break
            if not thread.is_alive():
                raise RuntimeError("OIDC API exited")
            time.sleep(0.05)
        else:
            raise RuntimeError("OIDC API startup deadline")
        bases["oidc"] = f"http://127.0.0.1:{port}"
        frontend = FRONTEND / ".next/standalone"
        import shutil

        shutil.copytree(
            FRONTEND / ".next/static", frontend / ".next/static", dirs_exist_ok=True
        )
        if (FRONTEND / "public").exists():
            shutil.copytree(
                FRONTEND / "public", frontend / "public", dirs_exist_ok=True
            )
        data = RUN / "next-runtime"
        (data / "tmp").mkdir(parents=True, exist_ok=True)
        (data / "cache").mkdir(exist_ok=True)
        web_port = free_port()
        env = browser_env(data)
        env.update(
            {
                "PORT": str(web_port),
                "HOSTNAME": "127.0.0.1",
                "HOMELAB_ANALYTICS_API_BASE_URL": bases["prefer-present"],
            }
        )
        next_log = (RUN / "acceptance-next.log").open("wb")
        next_process = subprocess.Popen(
            [NODE, str(frontend / "server.js")],
            cwd=frontend,
            env=env,
            stdout=next_log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        web = f"http://127.0.0.1:{web_port}"
        trace("next_start", pid=next_process.pid, port=web_port)
        for _ in range(200):
            if next_process.poll() is not None:
                raise RuntimeError("Next exited")
            try:
                response = httpx.get(web + "/login", timeout=1, trust_env=False)
                if response.status_code == 200:
                    break
            except httpx.TransportError:
                pass
            time.sleep(0.05)
        else:
            raise RuntimeError("Next startup deadline")
        trace("next_health", status=response.status_code)
        yield {
            "bases": bases,
            "runs": runs,
            "rows": rows,
            "history": history,
            "pg": pg,
            "ts": ts,
            "snapshot_hash": before_hash,
            "warehouse_snapshot_hash": hashlib.sha256(
                json.dumps(
                    ts.store.fetchall_dicts(
                        "SELECT * FROM reporting_publication_snapshot"
                    ),
                    sort_keys=True,
                    default=str,
                ).encode()
            ).hexdigest(),
            "web": web,
            "runtime": data,
            "issuer": issuer,
        }
    finally:
        errors = []
        try:
            if next_process is not None:
                stop_group(next_process)
                trace("next_stopped", pid=next_process.pid)
        except BaseException as exc:
            errors.append("Next cleanup: " + repr(exc))
        finally:
            if next_log is not None:
                next_log.close()
        for server, thread, port in reversed(servers):
            server.should_exit = True
            thread.join(10)
            trace("api_stopped", port=port, absent=not thread.is_alive())
            if thread.is_alive():
                errors.append("API thread leaked")
        try:
            deadline = time.monotonic() + 2
            removed_ids = []
            while time.monotonic() < deadline:
                listed = docker("ps", "-a", "--no-trunc", "--filter", "name=^/" + name + "$", "--format", "{{.ID}}")
                if listed.returncode:
                    raise RuntimeError("postgres container query failed")
                ids = listed.stdout.split()
                if len(ids) > 1:
                    raise RuntimeError("postgres container identity ambiguous")
                if ids:
                    actual = ids[0]
                    state = docker("inspect", "--format", '{{ index .Config.Labels "hla.priority.owner" }}', actual)
                    if state.returncode or state.stdout.strip() != name:
                        raise RuntimeError("postgres owner mismatch")
                    if identifier and actual != identifier:
                        raise RuntimeError("postgres container ID changed")
                    removed = docker("rm", "-f", actual)
                    if removed.returncode:
                        raise RuntimeError("postgres removal failed")
                    removed_ids.append(actual)
                time.sleep(.1)
            check = docker("ps", "-a", "--no-trunc", "--filter", "name=^/" + name + "$", "--format", "{{.ID}}")
            if check.returncode or check.stdout.strip():
                raise RuntimeError("postgres container survived cleanup")
            trace("cleanup", container=identifier, removed_ids=removed_ids, absent=True)
        except BaseException as exc:
            errors.append("postgres cleanup: " + repr(exc))
        if errors:
            raise RuntimeError("; ".join(errors))


@contextmanager
def login(base, role):
    client = httpx.Client(base_url=base, trust_env=False, timeout=15)
    try:
        response = client.post(
            "/auth/login", json={"username": "fixture-" + role, "password": PASSWORD}
        )
        trace("login_status", role=role, status=response.status_code)
        assert response.status_code == 200
        yield client
    finally:
        client.close()


def get(client, path, **kwargs):
    response = client.get(path, **kwargs)
    trace(
        "http_result",
        path=path,
        params=kwargs.get("params"),
        status=response.status_code,
        body=response.text,
    )
    return response


def priority(rows):
    def key(row):
        s = row.get("severity")
        rank = {3: 0, 2: 1, 1: 2}.get(s, 3) if type(s) is int else 3

        def text(value):
            return (value is None, str(value) if value is not None else "")

        return (
            rank,
            *(
                text(row.get(k))
                for k in ("item_type", "title", "item_id", "detail", "source_domain")
            ),
        )

    return sorted(rows, key=key)


def require_hash(data, expected):
    if hashlib.sha256(data).hexdigest() != expected:
        raise RuntimeError("bound fixture hash mismatch")


def require_browser_evidence(status, browser_pids, output, detail):
    if status != 0 or len(browser_pids) != 1 or not output.is_file():
        raise RuntimeError("browser bootstrap failed: " + detail)


def test_infrastructure_guards_reject_unavailable_hash_and_noop(tmp_path):
    good = b"bound synthetic fixture"
    require_hash(good, hashlib.sha256(good).hexdigest())
    with pytest.raises(RuntimeError, match="hash mismatch"):
        require_hash(good + b"corrupt", hashlib.sha256(good).hexdigest())
    with pytest.raises(httpx.TransportError):
        httpx.get(f"http://127.0.0.1:{free_port()}/health", trust_env=False, timeout=1)
    empty = subprocess.run(
        [NODE, "-e", ""], cwd=tmp_path, capture_output=True, text=True, timeout=10
    )
    assert empty.returncode == 0
    with pytest.raises(RuntimeError, match="browser bootstrap failed"):
        require_browser_evidence(
            empty.returncode, [], tmp_path / "missing.json", empty.stdout
        )
    trace("guard_falsified", hash_mismatch=True, unavailable=True, noop_browser=True)


def test_priority_oracle_rejects_inversion():
    high = {
        "item_id": "high",
        "severity": 3,
        "item_type": "review",
        "title": "high",
        "detail": "",
        "source_domain": "utilities",
    }
    low = {
        "item_id": "low",
        "severity": 1,
        "item_type": "payment",
        "title": "low",
        "detail": "",
        "source_domain": "finance",
    }
    assert ids(priority([low, high])) == ["high", "low"]
    with pytest.raises(AssertionError):
        assert ids([low, high]) == ids(priority([low, high]))
    trace("guard_falsified", inverted_priority=True)


def assert_source_values(actual, expected):
    fields = ("item_id", "item_type", "title", "detail", "source_domain", "severity")

    def population(rows):
        return Counter(tuple(row.get(field) for field in fields) for row in rows)

    assert population(actual) == population(expected)


def test_source_value_guard_rejects_tampering():
    original = [{"item_id": "a", "severity": 3, "source_domain": "utilities"}]
    assert_source_values(original, original)
    for changed in (dict(original[0], severity=1), dict(original[0], source_domain="finance")):
        with pytest.raises(AssertionError):
            assert_source_values([changed], original)
    trace("guard_falsified", changed_severity=True, changed_domain=True)


class SemanticPriorityFailure(AssertionError):
    """A specific observed priority or label defect, after controls succeeded."""


def semantic_priority(condition, category):
    if not condition:
        raise SemanticPriorityFailure("HLA_SEMANTIC_PRIORITY:" + category)


def ids(rows):
    return [row["item_id"] for row in rows]


@pytest.mark.parametrize(
    "mode", ["warehouse", "published", "prefer-present", "prefer-fallback"]
)
def test_positive_auth_and_current_population(world, mode):
    base = world["bases"][mode]
    unauth = httpx.get(base + "/reports/attention-items", trust_env=False, timeout=10)
    trace("unauth", mode=mode, status=unauth.status_code)
    assert unauth.status_code == 401
    with login(base, "reader") as client:
        response = get(client, "/reports/attention-items")
        assert response.status_code == 200
        body = response.json()
        assert body["as_of_status"] == "current" and len(body["rows"]) == 9
        assert_source_values(body["rows"], world["rows"])


@pytest.mark.parametrize(
    "mode", ["warehouse", "published", "prefer-present", "prefer-fallback"]
)
def test_current_priority_and_tie_identity(world, mode):
    with login(world["bases"][mode], "reader") as client:
        response = get(client, "/reports/attention-items")
        assert response.status_code == 200
        rows = response.json()["rows"]
        assert len(rows) == 9 and set(ids(rows)) == set(ids(world["rows"]))
        semantic_priority(ids(rows) == ids(priority(rows)), "ordering")


@pytest.mark.parametrize(
    "mode", ["warehouse", "published", "prefer-present", "prefer-fallback"]
)
def test_historical_priority_and_snapshot_immutable(world, mode):
    with login(world["bases"][mode], "reader") as client:
        response = get(client, "/reports/attention-items", params={"as_of": "2020-02"})
        assert response.status_code == 200
        body = response.json()
        rows = body["rows"]
        assert body["as_of_status"] == "snapshot" and len(rows) == 5
        assert (
            body["snapshot"]["projected"]
            and "severity" in body["snapshot"]["missing_columns"]
        )
        assert any(row.get("severity") is None for row in rows)
        assert any(row.get("severity") == 7 for row in rows)
        semantic_priority(ids(rows) == ids(priority(rows)), "ordering")
    after = world["pg"].fetchall_dicts("SELECT * FROM reporting_publication_snapshot")
    assert (
        hashlib.sha256(
            json.dumps(after, sort_keys=True, default=str).encode()
        ).hexdigest()
        == world["snapshot_hash"]
    )


@pytest.mark.parametrize(
    "mode", ["warehouse", "published", "prefer-present", "prefer-fallback"]
)
def test_no_history_is_empty_and_not_current(world, mode):
    with login(world["bases"][mode], "reader") as client:
        response = get(client, "/reports/attention-items", params={"as_of": "2020-01"})
        assert response.status_code == 200
        assert (
            response.json()["as_of_status"] == "no_history"
            and response.json()["rows"] == []
        )


@pytest.mark.parametrize("mode", ["warehouse", "published"])
def test_snapshot_read_preserves_saved_bytes(world, mode):
    with login(world["bases"][mode], "reader") as client:
        response = get(client, "/reports/attention-items", params={"as_of": "2020-02"})
        assert response.status_code == 200
        body = response.json()
        assert body["as_of_status"] == "snapshot" and len(body["rows"]) == 5
        assert (
            body["snapshot"]["projected"]
            and "severity" in body["snapshot"]["missing_columns"]
        )
        assert {row.get("severity") for row in body["rows"]} >= {None, 7}
        assert_source_values(body["rows"], world["history"])
    if mode == "published":
        rows = world["pg"].fetchall_dicts(
            "SELECT * FROM reporting_publication_snapshot"
        )
        expected = world["snapshot_hash"]
    else:
        rows = world["ts"].store.fetchall_dicts(
            "SELECT * FROM reporting_publication_snapshot"
        )
        expected = world["warehouse_snapshot_hash"]
    assert (
        hashlib.sha256(
            json.dumps(rows, sort_keys=True, default=str).encode()
        ).hexdigest()
        == expected
    )


@pytest.mark.parametrize("mode", ["warehouse", "published"])
def test_reversed_tie_insertion_real_http(world, mode):
    observed = []
    for order in (("tie-z", "tie-a"), ("tie-a", "tie-z")):
        ts = TransformationService(DuckDBStore.memory())
        for identifier in order:
            ts.store.execute(
                "INSERT INTO mart_open_attention_items VALUES (?, ?, ?, ?, ?, ?)",
                [identifier, "anomaly", "Same title", "Same detail", 2, "finance"],
            )
        pg = PostgresReportingStore(world["pg"].dsn, schema="ties_" + uuid.uuid4().hex)
        published = ReportingService(
            ts, publication_store=pg, access_mode=ReportingAccessMode.PUBLISHED
        )
        published.publish_publications(["mart_open_attention_items"])
        service = (
            published
            if mode == "published"
            else ReportingService(ts, access_mode=ReportingAccessMode.WAREHOUSE)
        )
        data = RUN / ("ties-" + uuid.uuid4().hex)
        app, _ = make_app(data, ts, service)
        port = free_port()
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        )
        thread = threading.Thread(target=server.run)
        thread.start()
        try:
            for _ in range(200):
                if server.started:
                    break
                if not thread.is_alive():
                    raise RuntimeError("tie API exited")
                time.sleep(0.05)
            else:
                raise RuntimeError("tie API startup deadline")
            with login(f"http://127.0.0.1:{port}", "reader") as client:
                response = get(client, "/reports/attention-items")
                assert response.status_code == 200
                actual = ids(response.json()["rows"])
                trace("tie_population", mode=mode, inserted=order, actual=actual)
                observed.append(actual)
        finally:
            server.should_exit = True
            thread.join(10)
            trace("tie_api_stopped", port=port, absent=not thread.is_alive())
            if thread.is_alive():
                raise RuntimeError("tie API thread leaked")
    semantic_priority(observed == [["tie-a", "tie-z"], ["tie-a", "tie-z"]], "tie-order")


@pytest.mark.parametrize("mode", ["warehouse", "published", "prefer-present", "prefer-fallback"])
def test_duplicate_rows_preserved_real_http(world, mode):
    ts = TransformationService(DuckDBStore.memory())
    inputs = [
        ("same-id", "anomaly", "Shared", "identical", 2, "finance"),
        ("same-id", "anomaly", "Shared", "identical", 2, "finance"),
        ("same-id", "anomaly", "Shared", "different detail", 2, "finance"),
        ("other-id", "review", "Other", "distinct domain", 3, "utilities"),
    ]
    for item in inputs:
        ts.store.execute("INSERT INTO mart_open_attention_items VALUES (?, ?, ?, ?, ?, ?)", list(item))
    expected = ts.store.fetchall_dicts("SELECT * FROM mart_open_attention_items")
    pg = PostgresReportingStore(world["pg"].dsn, schema="duplicates_" + uuid.uuid4().hex)
    published = ReportingService(ts, publication_store=pg, access_mode=ReportingAccessMode.PUBLISHED)
    published.publish_publications(["mart_open_attention_items"])
    empty = PostgresReportingStore(world["pg"].dsn, schema="duplicates_empty_" + uuid.uuid4().hex)
    services = {
        "warehouse": ReportingService(ts, access_mode=ReportingAccessMode.WAREHOUSE),
        "published": published,
        "prefer-present": ReportingService(ts, publication_store=pg, access_mode=ReportingAccessMode.PREFER_PUBLISHED),
        "prefer-fallback": ReportingService(ts, publication_store=empty, access_mode=ReportingAccessMode.PREFER_PUBLISHED),
    }
    app, _ = make_app(RUN / ("duplicates-" + uuid.uuid4().hex), ts, services[mode])
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run)
    thread.start()
    try:
        for _ in range(200):
            if server.started:
                break
            if not thread.is_alive():
                raise RuntimeError("duplicate API exited")
            time.sleep(.05)
        else:
            raise RuntimeError("duplicate API startup deadline")
        with login(f"http://127.0.0.1:{port}", "reader") as client:
            response = get(client, "/reports/attention-items")
            assert response.status_code == 200
            rows = response.json()["rows"]
            trace("duplicate_population", mode=mode, expected=expected, actual=rows)
            assert len(rows) == 4
            assert_source_values(rows, expected)
            deduplicated = []
            for row in rows:
                if row not in deduplicated:
                    deduplicated.append(row)
            assert len(deduplicated) == 3
            with pytest.raises(AssertionError):
                assert_source_values(deduplicated, expected)
            trace("guard_falsified", mode=mode, delivered_deduplicated_count=len(deduplicated), original_count=len(rows))
    finally:
        server.should_exit = True
        thread.join(10)
        trace("duplicate_api_stopped", port=port, absent=not thread.is_alive())
        if thread.is_alive():
            raise RuntimeError("duplicate API thread leaked")


def test_oidc_publication_permission(world):
    issuer = world["issuer"]
    base = world["bases"]["oidc"]

    def token(permissions):
        return issuer.issue_token(
            subject="fixture-reader",
            username="fixture-reader",
            audience=issuer.api_audience,
            groups=(),
            extra_claims={"hla_permissions": permissions},
        )

    denied = httpx.get(
        base + "/reports/attention-items",
        headers={"authorization": "Bearer " + token([])},
        trust_env=False,
        timeout=10,
    )
    allowed = httpx.get(
        base + "/reports/attention-items",
        headers={
            "authorization": "Bearer "
            + token(["reports.read.publication.attention-items"])
        },
        trust_env=False,
        timeout=10,
    )
    trace("oidc_permission", denied=denied.status_code, allowed=allowed.status_code)
    assert denied.status_code == 403 and allowed.status_code == 200
    assert len(allowed.json()["rows"]) == 9


def test_assistant_evidence_prioritizes_same_real_rows(world):
    with login(world["bases"]["prefer-present"], "admin") as client:
        response = get(
            client,
            "/api/assistant/answer",
            params={"question": "operations", "domain": "operations"},
        )
        assert response.status_code == 200
        rows = response.json()["evidence"]["open_attention_items"]
        assert len(rows) == 3
        semantic_priority(all(row["severity"] == 3 for row in rows), "assistant-order")


BROWSER_SCRIPT = r"""
const {chromium}=require(process.env.FRONTEND+'/node_modules/playwright');
const fs=require('node:fs');
(async()=>{
 const server=await chromium.launchServer({host:'127.0.0.1',port:0,headless:true,args:['--no-sandbox']});
 console.log('BROWSER_PID='+server.process().pid);
 const browser=await chromium.connect(server.wsEndpoint());
 let result={};
 try {
  const context=await browser.newContext();
  const page=await context.newPage();
  await page.goto(process.env.WEB+'/login');
  await page.locator('#username').fill('fixture-admin');
  await page.locator('#password').fill('synthetic-local-password');
  await Promise.all([page.waitForURL(url=>!url.pathname.startsWith('/login')),page.locator('button[type=submit]').click()]);
  result.loginPath=new URL(page.url()).pathname;
  const pages=[
   ['operating','/operating-picture','Decisions pending','.attentionRow'],
   ['home','/','Items to review','ul > li'],
   ['first','/first-answer','Items requiring review','.stack.compactStack > div'],
   ['ingest','/ingest-summary/'+process.env.RUN_ID,'Items to review after this upload','.stack.compactStack > div'],
   ['history','/?asof=2020-02','Items to review','ul > li']
  ];
  for(const [name,url,heading,selector] of pages){
   const direct=await context.request.get(process.env.WEB+url);
   const response=await page.goto(process.env.WEB+url,{waitUntil:'networkidle'});
   const correct=page.locator('article').filter({has:page.getByRole('heading',{name:heading,exact:false})});
   const count=await correct.count();
   const rows=[];
   if(count===1){
    for(const row of await correct.locator(selector).all()){
     rows.push({text:(await row.innerText()).replace(/\s+/g,' ').trim(),warning:await row.locator('.status-failed').count(),pills:await row.locator('.pill').allTextContents()});
    }
   }
   result[name]={status:direct.status(),navigationStatus:response?response.status():null,path:new URL(page.url()).pathname,sectionCount:count,rows};
  }
  await context.close();
 } finally {
  fs.writeFileSync(process.env.OUTPUT,JSON.stringify(result,null,2));
  console.log('RESULT_WRITTEN='+process.env.OUTPUT);
  await browser.close();
  await server.close();
 }
})().catch(e=>{console.error(e.stack||String(e));process.exitCode=1});
"""


def browser_container_state(name):
    result = docker("ps", "-a", "--no-trunc", "--filter", "name=^/" + name + "$", "--format", "{{.ID}}")
    if result.returncode:
        raise RuntimeError("browser container query failed")
    ids = result.stdout.split()
    if not ids:
        return None
    if len(ids) != 1 or not re.fullmatch(r"[a-f0-9]{64}", ids[0]):
        raise RuntimeError("browser container identity ambiguous")
    detail = docker("inspect", "--format", '{{.State.Running}} {{index .Config.Labels "hla.browser.owner"}}', ids[0])
    if detail.returncode or detail.stdout.split() not in (["true", name], ["false", name]):
        raise RuntimeError("browser container label mismatch")
    return ids[0], detail.stdout.split()[0] == "true"


def browser_command(script, env, native, name):
    if native:
        return [NODE, str(script)]
    command = ["docker", "run", "--pull=never", "--name", name, "--label", "hla.browser.owner=" + name, "--network", "host", "-v", str(ROOT) + ":" + str(ROOT), "-v", str(FRONTEND) + ":" + str(FRONTEND) + ":ro"]
    for key in ("FRONTEND", "WEB", "RUN_ID", "OUTPUT"):
        if key in env:
            command += ["-e", key + "=" + env[key]]
    command += ["sha256:b0ab6f3cb99aa7803adbc14d9027ec1785fc6e433b97e134e0f8fe61683b6b53", "node", str(script)]
    return command


def run_browser(command, env, log, *, force_owner_failure=False, container_name=None):
    libc = ctypes.CDLL(None)
    prior = ctypes.c_int()
    if libc.prctl(37, ctypes.byref(prior), 0, 0, 0) != 0:
        raise RuntimeError("cannot read subreaper state")
    if libc.prctl(36, 1, 0, 0, 0) != 0:
        raise RuntimeError("cannot set subreaper state")
    process = None
    try:
        with log.open("wb") as stream:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                env=env,
                stdout=stream,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            trace("browser_start", pid=process.pid)
            if force_owner_failure:
                deadline = time.monotonic() + 30
                while (
                    time.monotonic() < deadline
                    and "GUARD_BROWSER_READY" not in log.read_text(errors="replace")
                ):
                    if process.poll() is not None:
                        raise RuntimeError("browser guard exited before readiness")
                    time.sleep(0.05)
                text = log.read_text(errors="replace")
                pids = re.findall(r"^BROWSER_PID=(\d+)$", text, re.MULTILINE)
                if "GUARD_BROWSER_READY" not in text or len(pids) != 1:
                    raise RuntimeError("browser guard unavailable")
                browser_pid = int(pids[0])
                if container_name is None:
                    os.killpg(browser_pid, signal.SIGSTOP)
                else:
                    before = browser_container_state(container_name)
                    if before is None or not before[1]:
                        raise RuntimeError("browser container was not running")
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
                if container_name is None:
                    os.killpg(browser_pid, 0)
                elif browser_container_state(container_name) != before:
                    raise RuntimeError("browser container did not survive client death")
                if container_name:
                    trace("guard_browser_container", name=container_name, identifier=before[0])
                trace(
                    "forced_browser_owner_failure",
                    node_pid=process.pid,
                    browser_pid=browser_pid,
                )
                raise RuntimeError("forced browser owner failure")
            try:
                status = process.wait(timeout=120)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("browser deadline exceeded") from exc
        trace("browser_exit", exit=status)
        return status
    finally:
        try:
            if process is not None:
                stop_group(process)
        finally:
            try:
                if container_name is None:
                    stop_browser_groups(log, env["TMPDIR"])
                else:
                    deadline = time.monotonic() + 2
                    removed_ids = []
                    while time.monotonic() < deadline:
                        state = browser_container_state(container_name)
                        if state:
                            removed = docker("rm", "-f", state[0])
                            if removed.returncode:
                                raise RuntimeError("browser container removal failed")
                            removed_ids.append(state[0])
                        time.sleep(0.1)
                    if browser_container_state(container_name) is not None:
                        raise RuntimeError("browser container leaked")
                    trace("browser_container_absent", name=container_name, removed_ids=removed_ids)
            finally:
                if libc.prctl(36, prior.value, 0, 0, 0) != 0:
                    raise RuntimeError("cannot restore subreaper state")


@pytest.fixture(scope="session")
def native_browser(world):
    script = RUN / "native-probe.cjs"
    script.write_text("const {chromium}=require(process.env.FRONTEND+'/node_modules/playwright');(async()=>{const b=await chromium.launchServer({host:'127.0.0.1',port:0,headless:true,args:['--no-sandbox']});console.log('BROWSER_PID='+b.process().pid);await b.close()})().catch(e=>{console.error(e);process.exit(1)})")
    env = browser_env(world["runtime"])
    env["FRONTEND"] = str(FRONTEND)
    status = run_browser([NODE, str(script)], env, RUN / "native-probe.log")
    native = status == 0 and not os.environ.get("HLA_FORCE_DOCKER_BROWSER")
    trace("browser_topology", native=native, probe_exit=status)
    return native


@pytest.fixture(scope="session")
def browser_result(world, native_browser):
    script = RUN / "acceptance-browser.cjs"
    script.write_text(BROWSER_SCRIPT)
    output = RUN / "acceptance-browser.json"
    log = RUN / "acceptance-browser.log"
    env = browser_env(world["runtime"])
    env.update(
        {
            "FRONTEND": str(FRONTEND),
            "WEB": world["web"],
            "RUN_ID": world["runs"]["prefer-present"],
            "OUTPUT": str(output),
        }
    )
    observations_before = sum(
        1
        for line in (RUN / "acceptance.trace.jsonl").read_text().splitlines()
        if json.loads(line).get("path") == "/reports/attention-items"
        and json.loads(line).get("status") == 200
    )
    name = None if native_browser else "hla-priority-browser-" + uuid.uuid4().hex
    status = run_browser(browser_command(script, env, native_browser, name), env, log, container_name=name)
    text = log.read_text(errors="replace")
    browser_pids = [
        int(value) for value in re.findall(r"^BROWSER_PID=(\d+)$", text, re.MULTILINE)
    ]
    require_browser_evidence(status, browser_pids, output, text)
    observations_after = sum(
        1
        for line in (RUN / "acceptance.trace.jsonl").read_text().splitlines()
        if json.loads(line).get("path") == "/reports/attention-items"
        and json.loads(line).get("status") == 200
    )
    trace(
        "browser_upstream_requests",
        before=observations_before,
        after=observations_after,
    )
    if observations_after - observations_before < 5:
        raise RuntimeError(
            "real Next did not request the actual attention API for each page"
        )
    return json.loads(output.read_text())


def test_browser_owner_failure_cleans_exact_group(world, native_browser):
    script = RUN / "browser-owner-failure.cjs"
    script.write_text(
        "const {chromium}=require(process.env.FRONTEND+'/node_modules/playwright');(async()=>{const server=await chromium.launchServer({host:'127.0.0.1',port:0,headless:true,args:['--no-sandbox']});console.log('BROWSER_PID='+server.process().pid);console.log('GUARD_BROWSER_READY');await new Promise(()=>{});})().catch(e=>{console.error(e);process.exit(1)});"
    )
    log = RUN / "browser-owner-failure.log"
    env = browser_env(world["runtime"])
    env["FRONTEND"] = str(FRONTEND)
    name = None if native_browser else "hla-priority-browser-" + uuid.uuid4().hex
    with pytest.raises(RuntimeError, match="forced browser owner failure"):
        run_browser(browser_command(script, env, native_browser, name), env, log, force_owner_failure=True, container_name=name)
    if name:
        assert browser_container_state(name) is None
        trace("browser_post_return_container_absent", name=name)
        return
    pids = re.findall(
        r"^BROWSER_PID=(\d+)$", log.read_text(errors="replace"), re.MULTILINE
    )
    assert len(pids) == 1
    try:
        os.killpg(int(pids[0]), 0)
    except ProcessLookupError:
        trace("browser_post_return_absent", pid=int(pids[0]))
    else:
        raise AssertionError("browser owner finalizer left the exact browser group")


def test_exited_leader_ignoring_child_is_cleaned(tmp_path):
    libc = ctypes.CDLL(None)
    prior = ctypes.c_int()
    assert libc.prctl(37, ctypes.byref(prior), 0, 0, 0) == 0
    assert libc.prctl(36, 1, 0, 0, 0) == 0
    ready = tmp_path / "child-ready"
    child = "import pathlib,signal,sys,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);pathlib.Path(sys.argv[1]).write_text('ready');time.sleep(60)"
    parent = "import pathlib,subprocess,sys,time\nsubprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]])\np=pathlib.Path(sys.argv[2])\nwhile not p.exists(): time.sleep(.05)\n"
    process = subprocess.Popen(
        [sys.executable, "-c", parent, child, str(ready)],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert process.wait(timeout=10) == 0 and ready.exists()
        os.killpg(process.pid, 0)
        stop_group(process)
        with pytest.raises(ProcessLookupError):
            os.killpg(process.pid, 0)
        trace("leader_exited_child_cleaned", pgid=process.pid)
    finally:
        try:
            stop_group(process)
        finally:
            assert libc.prctl(36, prior.value, 0, 0, 0) == 0


def actual_rows(world):
    with login(world["bases"]["prefer-present"], "admin") as client:
        response = get(client, "/reports/attention-items")
        assert response.status_code == 200
        return response.json()["rows"]


def display_titles(rows, observed):
    titles = [row["title"] for row in rows]
    result = []
    for visible in observed:
        matches = [title for title in titles if title in visible["text"]]
        assert len(set(matches)) == 1, (visible, matches)
        result.append(matches[0])
    return result


@pytest.mark.parametrize(
    "page,limit", [("operating", 8), ("home", 9), ("first", 6), ("ingest", 5)]
)
def test_browser_positive_real_page_population(world, browser_result, page, limit):
    value = browser_result[page]
    assert not browser_result["loginPath"].startswith("/login")
    assert value["status"] == 200 and value["sectionCount"] == 1
    assert len(value["rows"]) == limit
    rows = actual_rows(world)
    assert len(rows) == 9 and len(display_titles(rows, value["rows"])) == limit
    trace("browser_population", page=page, result=value)


@pytest.mark.parametrize(
    "page,limit", [("operating", 8), ("home", 9), ("first", 6), ("ingest", 5)]
)
def test_browser_priority_and_labels(world, browser_result, page, limit):
    value = browser_result[page]
    assert value["status"] == 200 and value["sectionCount"] == 1
    rows = actual_rows(world)
    expected = priority(rows)[:limit]
    semantic_priority(display_titles(rows, value["rows"]) == [row["title"] for row in expected], "browser-order")
    if page == "operating":
        semantic_priority(
            [row["pills"][0].lower() for row in value["rows"]]
            == [{3: "urgent", 2: "soon", 1: "watch"}[row["severity"]] for row in expected],
            "browser-label",
        )
    else:
        semantic_priority(
            [row["warning"] > 0 for row in value["rows"]]
            == [row["severity"] == 3 for row in expected],
            "browser-label",
        )


def test_browser_history_unrecognized_is_visible_and_neutral(world, browser_result):
    value = browser_result["history"]
    assert (
        value["status"] == 200
        and value["sectionCount"] == 1
        and len(value["rows"]) == 5
    )
    matching = [
        row
        for row in value["rows"]
        if "Unknown Priority Fixture" in row["text"]
        or "Missing Priority Fixture" in row["text"]
    ]
    assert len(matching) == 2
    semantic_priority(
        all("unranked" in row["text"].lower() and row["warning"] == 0 for row in matching),
        "unknown-label",
    )


# Remaining consumers of this same overview publication. The original forty
# cases above retain their fixture and assertions; only this owned publication
# is replaced temporarily, and its complete row multiset is restored afterward.
@contextmanager
def consumer_publication(world, rows):
    from packages.domains.overview.pipelines.overview_models import MART_OPEN_ATTENTION_ITEMS_COLUMNS

    pg = world["pg"]
    saved = pg.fetchall_dicts("SELECT * FROM mart_open_attention_items")
    snapshot_before = pg.fetchall_dicts("SELECT * FROM reporting_publication_snapshot")
    try:
        pg.replace_rows("mart_open_attention_items", MART_OPEN_ATTENTION_ITEMS_COLUMNS, rows)
        with login(world["bases"]["prefer-present"], "admin") as client:
            response = get(client, "/reports/attention-items")
            assert response.status_code == 200
            delivered = response.json()["rows"]
        assert_source_values(delivered, rows)
        trace("consumer_publication", expected=rows, delivered=delivered)
        yield delivered
    finally:
        pg.replace_rows("mart_open_attention_items", MART_OPEN_ATTENTION_ITEMS_COLUMNS, saved)
        restored = pg.fetchall_dicts("SELECT * FROM mart_open_attention_items")
        assert_source_values(restored, saved)
        assert pg.fetchall_dicts("SELECT * FROM reporting_publication_snapshot") == snapshot_before
        trace("consumer_publication_restored", count=len(restored), snapshot_unchanged=True)


def consumer_rows():
    def row(identifier, title, severity, item_type, domain):
        return {"item_id": identifier, "item_type": item_type, "title": title,
                "detail": "Synthetic consumer fixture", "severity": severity,
                "source_domain": domain}
    return [
        row("consumer-unknown", "Consumer Unknown", 7, "anomaly", "finance"),
        row("consumer-high", "Consumer High", 3, "contract_review", "utilities"),
        row("consumer-tie-z", "Consumer Twin", 3, "anomaly", "utilities"),
        row("consumer-tie-a", "Consumer Twin", 3, "anomaly", "finance"),
        row("consumer-medium", "Consumer Medium", 2, "contract_review", "utilities"),
        row("consumer-low", "Consumer Low", 1, "upcoming_cost", "finance"),
    ]


CONSUMER_BROWSER_SCRIPT = r"""
const {chromium}=require(process.env.FRONTEND+'/node_modules/playwright');
const fs=require('node:fs');
(async()=>{
 const server=await chromium.launchServer({host:'127.0.0.1',port:0,headless:true,args:['--no-sandbox']});
 console.log('BROWSER_PID='+server.process().pid);
 const browser=await chromium.connect(server.wsEndpoint());
 let result={};
 try{
  const context=await browser.newContext();
  const page=await context.newPage();
  await page.goto(process.env.WEB+'/login');
  await page.locator('#username').fill('fixture-admin');
  await page.locator('#password').fill('synthetic-local-password');
  await Promise.all([page.waitForURL(url=>!url.pathname.startsWith('/login')),page.locator('button[type=submit]').click()]);
  result.loginPath=new URL(page.url()).pathname;
  const mode=__CONSUMER_MODE__;
  for(const [name,url] of (mode==='mixed'?[['review','/review'],['console','/console']]:[['wallboard','/wallboard?compact=1']])){
   const direct=await context.request.get(process.env.WEB+url);
   const response=await page.goto(process.env.WEB+url,{waitUntil:'networkidle'});
   let rows=[],count=0,tone=null;
   if(name==='review'){
    const section=page.locator('article').filter({has:page.getByRole('heading',{name:'Attention items',exact:true})});
    count=await section.count();
    if(count===1)for(const tr of await section.locator('tbody > tr').all()){
     const cells=await tr.locator('td').allTextContents();
     rows.push({title:cells[1].trim(),domain:cells[2].trim(),warning:await tr.locator('.status-failed').count()});
    }
   }else if(name==='console'){
    const section=page.locator('.consoleAttentionList');count=await section.count();
    if(count===1)for(const row of await section.locator('.consoleAttentionItem').all()){
     rows.push({title:(await row.locator('.consoleAttentionTitle').innerText()).trim(),rank:(await row.locator('.consoleAttentionRank').innerText()).trim(),dataRank:await row.getAttribute('data-rank')});
    }
   }else{
    const section=page.locator('section.wallTile').filter({has:page.getByRole('heading',{name:'Needs a decision',exact:true})});
    count=await section.count();
    if(count===1){tone=await section.getAttribute('data-tone');rows=[{text:(await section.innerText()).replace(/\s+/g,' ').trim(),count:(await section.locator('.wallBig').innerText()).trim()}];}
   }
   result[name]={status:direct.status(),navigationStatus:response?response.status():null,path:new URL(page.url()).pathname,sectionCount:count,rows,tone};
  }
  await context.close();
 }finally{
  fs.writeFileSync(process.env.OUTPUT,JSON.stringify(result,null,2));
  console.log('RESULT_WRITTEN='+process.env.OUTPUT);await browser.close();await server.close();
 }
})().catch(e=>{console.error(e.stack||String(e));process.exitCode=1});
"""


def capture_consumer_browser(world, native_browser, mode):
    label = mode + "-" + uuid.uuid4().hex
    script = RUN / (label + ".cjs")
    script.write_text(CONSUMER_BROWSER_SCRIPT.replace("__CONSUMER_MODE__", json.dumps(mode)))
    output = RUN / (label + ".json")
    log = RUN / (label + ".log")
    env = browser_env(world["runtime"])
    env.update(FRONTEND=str(FRONTEND), WEB=world["web"], OUTPUT=str(output))
    before = sum(json.loads(line).get("path") == "/reports/attention-items" and json.loads(line).get("status") == 200
                 for line in (RUN / "acceptance.trace.jsonl").read_text().splitlines())
    name = None if native_browser else "hla-priority-browser-" + uuid.uuid4().hex
    status = run_browser(browser_command(script, env, native_browser, name), env, log, container_name=name)
    text = log.read_text(errors="replace")
    pids = [int(v) for v in re.findall(r"^BROWSER_PID=(\d+)$", text, re.MULTILINE)]
    require_browser_evidence(status, pids, output, text)
    after = sum(json.loads(line).get("path") == "/reports/attention-items" and json.loads(line).get("status") == 200
                for line in (RUN / "acceptance.trace.jsonl").read_text().splitlines())
    if after-before < (2 if mode == "mixed" else 1):
        raise RuntimeError("consumer Next pages did not read the actual attention API")
    result = json.loads(output.read_text())
    assert not result["loginPath"].startswith("/login")
    for key in ("review", "console") if mode == "mixed" else ("wallboard",):
        assert result[key]["status"] == 200 and result[key]["sectionCount"] == 1
    trace("consumer_browser", mode=mode, observations=after-before, result=result)
    return result


def compose_attention(rows):
    from datetime import UTC, date, datetime
    from packages.application.use_cases.morning_brief import (
        BriefInputs, ConfidenceEvidence, PublicationInput, compose_morning_brief,
    )
    from packages.application.use_cases.morning_brief_sections import ATTENTION_ITEMS_KEY

    confidence = ConfidenceEvidence(
        publication_key=ATTENTION_ITEMS_KEY, verdict="trustworthy", freshness_state="current",
        completeness_pct=100, assessed_at=datetime(2026, 11, 15, tzinfo=UTC),
        quality_flags={"validation_errors": 0, "rejected_runs": 0},
        contributing_run_ids=("synthetic-consumer-run",), source_states=(("synthetic", "current"),),
    )
    inputs = BriefInputs(as_of=date(2026, 11, 15), generated_at=datetime(2026, 11, 15, 6, tzinfo=UTC),
                         publications={ATTENTION_ITEMS_KEY: PublicationInput(ATTENTION_ITEMS_KEY, tuple(rows), confidence)},
                         policies=(), sources=())
    brief = compose_morning_brief(inputs)
    section = next(section for section in brief.sections if section.key == "attention")
    return [{"item_id": item.item_id, "headline": item.headline, "severity": str(item.severity)}
            for item in section.items]


@pytest.fixture(scope="session")
def consumer_result(world, native_browser):
    rows = consumer_rows()
    with consumer_publication(world, rows) as delivered:
        mixed = capture_consumer_browser(world, native_browser, "mixed")
        with login(world["bases"]["prefer-present"], "admin") as client:
            response = get(client, "/api/assistant/answer", params={"question": "operations", "domain": "operations"})
            assert response.status_code == 200
            answer = response.json()
        briefing = compose_attention(delivered)
        known = [r for r in delivered if type(r.get("severity")) is int and r["severity"] in (1, 2, 3)]
        known_briefing = compose_attention(known)
        unknown_briefing = compose_attention([r for r in delivered if r["severity"] == 7])
    walls = {}
    for severity in (7, 2, 3):
        selected = [dict(rows[0], item_id="wall-"+str(severity), title="Wall Priority "+str(severity), severity=severity)]
        with consumer_publication(world, selected):
            walls[severity] = capture_consumer_browser(world, native_browser, "wall-"+str(severity))["wallboard"]
    restored = actual_rows(world)
    assert_source_values(restored, world["rows"])
    trace("consumer_capture_complete", mixed=mixed, answer=answer, briefing=briefing, walls=walls)
    return {"rows": rows, "delivered": delivered, "mixed": mixed, "answer": answer,
            "briefing": briefing, "known_briefing": known_briefing, "unknown_briefing": unknown_briefing, "walls": walls,
            "restored": restored}


def test_consumers_real_api_population_and_restore(world, consumer_result):
    assert len(consumer_result["delivered"]) == 6
    assert_source_values(consumer_result["delivered"], consumer_result["rows"])
    assert_source_values(consumer_result["restored"], world["rows"])
    assert len(consumer_result["mixed"]["review"]["rows"]) == 6
    assert len(consumer_result["mixed"]["console"]["rows"]) == 6
    assert len(consumer_result["answer"]["evidence"]["open_attention_items"]) == 3


def test_review_unknown_and_tie_order(consumer_result):
    actual = [(r["title"], r["domain"]) for r in consumer_result["mixed"]["review"]["rows"]]
    expected = [(r["title"], r["source_domain"]) for r in priority(consumer_result["rows"])]
    assert Counter(actual) == Counter(expected)
    semantic_priority(actual == expected, "consumer-order")


def test_console_unknown_order_and_labels(consumer_result):
    actual = consumer_result["mixed"]["console"]["rows"]
    expected = priority(consumer_result["rows"])
    assert Counter(r["title"] for r in actual) == Counter(r["title"] for r in expected)
    semantic_priority([r["title"] for r in actual] == [r["title"] for r in expected], "consumer-order")
    expected_ranks = [{3: "s1", 2: "s2", 1: "s3"}.get(r["severity"], "unranked") for r in expected]
    semantic_priority([r["rank"].lower() for r in actual] == expected_ranks, "console-label")


def test_wallboard_unknown_does_not_warn(consumer_result):
    value = consumer_result["walls"][7]
    assert len(value["rows"]) == 1 and value["rows"][0]["count"] == "1"
    assert "Wall Priority 7" in value["rows"][0]["text"]
    semantic_priority(value["tone"] != "warn", "wallboard-unknown")


@pytest.mark.parametrize("severity", [2, 3])
def test_wallboard_recognized_warning_threshold(consumer_result, severity):
    value = consumer_result["walls"][severity]
    assert value["rows"][0]["count"] == "1" and "Wall Priority "+str(severity) in value["rows"][0]["text"]
    assert value["tone"] == "warn"


def test_briefing_known_severity_conventions(consumer_result):
    by_id = {r["item_id"]: r for r in consumer_result["known_briefing"]}
    assert by_id["attention:consumer-high"]["severity"] == "warning"
    assert by_id["attention:consumer-medium"]["severity"] == "notice"
    assert by_id["attention:consumer-low"]["severity"] == "info"


def test_briefing_unknown_and_tie_order(consumer_result):
    expected = ["attention:"+r["item_id"] for r in priority(consumer_result["rows"])[:5]]
    actual = [r["item_id"] for r in consumer_result["briefing"]]
    assert len(actual) == 5
    semantic_priority(actual == expected, "briefing-order")


def test_assistant_headline_and_evidence_use_same_priority(consumer_result):
    body = consumer_result["answer"]
    expected = priority(consumer_result["rows"])
    semantic_priority(expected[0]["title"] in body["answer"] and "(severity 3)" in body["answer"], "assistant-headline")
    semantic_priority(ids(body["evidence"]["open_attention_items"]) == ids(expected[:3]), "assistant-order")


def test_browser_history_complete_order(world, browser_result):
    value = browser_result["history"]
    assert value["status"] == 200 and value["sectionCount"] == 1 and len(value["rows"]) == 5
    actual = display_titles(world["history"], value["rows"])
    semantic_priority(actual == [r["title"] for r in priority(world["history"])], "history-order")


def test_review_recognized_warning_and_unknown_neutral(consumer_result):
    actual = consumer_result["mixed"]["review"]["rows"]
    expected = {(r["title"], r["source_domain"]): r["severity"] == 3 for r in consumer_result["rows"]}
    assert Counter((r["title"], r["domain"]) for r in actual) == Counter(expected.keys())
    semantic_priority(all((r["warning"] > 0) == expected[(r["title"], r["domain"])] for r in actual), "review-label")


def test_console_recognized_and_unknown_labels(consumer_result):
    actual = consumer_result["mixed"]["console"]["rows"]
    expected = {r["title"]: {3: "s1", 2: "s2", 1: "s3"}.get(r["severity"], "unranked") for r in consumer_result["rows"]}
    assert Counter(r["title"] for r in actual) == Counter(r["title"] for r in consumer_result["rows"])
    semantic_priority(all(r["rank"].lower() == expected[r["title"]] for r in actual), "console-label")


def test_briefing_unknown_only_is_neutral(consumer_result):
    assert consumer_result["unknown_briefing"] == [{"item_id": "attention:consumer-unknown", "headline": "Consumer Unknown", "severity": "info"}]
'''


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checked_source(text, expected):
    data = text.encode("utf-8")
    if digest(data) != expected:
        raise RuntimeError("bound acceptance source mismatch")
    return data


def extract_node(archive, destination):
    if digest(archive.read_bytes()) != NODE_SHA256:
        raise RuntimeError("Node archive checksum mismatch")
    with tarfile.open(archive, "r:xz") as package:
        package.extractall(destination, filter="data")
    return destination / "node-v20.20.1-linux-x64/bin/node"



def gate():
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise RuntimeError("Linux x86_64 required")
    runner = checked_source(RUNNER_SOURCE, RUNNER_SHA256)
    test = checked_source(TEST_SOURCE, TEST_SHA256)
    repo = Path.cwd().resolve()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repo, text=True):
        raise RuntimeError("tracked source must be clean")
    browser_cache = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or Path.home() / ".cache/ms-playwright").resolve()
    root = Path(tempfile.mkdtemp(prefix="hla-overview-priority-gate-"))
    print("HLA_ACCEPTANCE_EVIDENCE=" + str(root), flush=True)
    for name in ("home", "cache", "tmp", "python"):
        (root / name).mkdir()
    env = {
        "HOME": str(root / "home"),
        "XDG_CACHE_HOME": str(root / "cache"),
        "UV_CACHE_DIR": str(root / "cache/uv"),
        "UV_PYTHON_INSTALL_DIR": str(root / "python"),
        "TMPDIR": str(root / "tmp"),
        "PATH": os.environ.get("PATH", os.defpath),
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    for key in ("SSL_CERT_FILE", "NIX_SSL_CERT_FILE"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    ca_bundle = os.environ.get("SSL_CERT_FILE") or os.environ.get("NIX_SSL_CERT_FILE")
    if not ca_bundle and Path("/etc/ssl/certs/ca-certificates.crt").is_file():
        ca_bundle = "/etc/ssl/certs/ca-certificates.crt"
    if ca_bundle:
        env["SSL_CERT_FILE"] = ca_bundle
    tls = ssl.create_default_context(cafile=ca_bundle)
    nix_lib = Path("/run/current-system/sw/share/nix-ld/lib")
    if (nix_lib / "ld.so").is_file():
        env["NIX_LD"] = str(nix_lib / "ld.so")
        env["NIX_LD_LIBRARY_PATH"] = str(nix_lib)
        env["LD_LIBRARY_PATH"] = str(nix_lib)
    archive = root / "node.tar.xz"
    (root / "run_acceptance.py").write_bytes(runner)
    (root / "test_overview_priority_acceptance.py").write_bytes(test)
    namespace = runpy.run_path(str(root / "run_acceptance.py"), run_name="owned_acceptance")
    owned_run = namespace["run"]
    try:
        with urllib.request.urlopen(NODE_URL, timeout=120, context=tls) as source, archive.open("wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
        node = extract_node(archive, root)
        result = owned_run("node-version", [str(node), "--version"], root, env, root)
        if result.returncode or result.stdout.strip() != "v20.20.1":
            raise RuntimeError("Node version check failed")
        shim = root / "node-shim"
        shim.mkdir()
        node_prefix = (
            ["env", "NIX_LD=" + str(nix_lib / "ld.so"), "NIX_LD_LIBRARY_PATH=" + str(nix_lib), str(node)]
            if (nix_lib / "ld.so").is_file()
            else [str(node)]
        )
        shim_node = shim / "node"
        shim_node.write_text("#!/bin/sh\nexec " + shlex.join(node_prefix) + ' "$@"\n')
        shim_node.chmod(0o755)
        shim_npm = shim / "npm"
        shim_npm.write_text("#!/bin/sh\nexec " + shlex.join([str(shim_node), str(node.parent.parent / "lib/node_modules/npm/bin/npm-cli.js")]) + ' "$@"\n')
        shim_npm.chmod(0o755)
        install = owned_run("python-install", ["uv", "python", "install", "3.12", "--no-bin"], root, env, root)
        if install.returncode:
            raise RuntimeError("UV Python installation failed")
        found = owned_run("python-find", ["uv", "python", "find", "--managed-python", "3.12"], root, env, root)
        if found.returncode or not found.stdout.strip():
            raise RuntimeError("UV Python 3.12 unavailable")
        python = Path(found.stdout.strip())
        original_argv = sys.argv
        old_env = os.environ.copy()
        try:
            os.environ.clear()
            os.environ.update(env)
            sys.argv = [str(root / "run_acceptance.py"), "--checkout", str(repo), "--output", str(root / "result"), "--commit", head, "--python", str(python), "--node", str(shim_node), "--browser-cache", str(browser_cache), "--test-sha256", TEST_SHA256]
            return namespace["main"]()
        finally:
            sys.argv = original_argv
            os.environ.clear()
            os.environ.update(old_env)
    finally:
        for item in (root / "python", root / "cache", root / "node-v20.20.1-linux-x64", root / "result/checkout/.venv", root / "result/checkout/apps/web/frontend/node_modules", root / "result/checkout/apps/web/frontend/.next", root / "result/cache"):
            if item.is_dir() and not item.is_symlink():
                shutil.rmtree(item)
        archive.unlink(missing_ok=True)


def test_overview_priority_gate():
    result = gate()
    if result not in (0, 1):
        raise RuntimeError("acceptance returned infrastructure status " + str(result))
    assert result == 0


if __name__ == "__main__":
    try:
        sys.exit(gate())
    except Exception as error:
        print("INFRASTRUCTURE:", type(error).__name__, str(error), file=sys.stderr)
        sys.exit(2)
