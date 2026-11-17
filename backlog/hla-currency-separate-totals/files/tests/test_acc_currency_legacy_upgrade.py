"""Independent candidate check for real existing-store upgrade and old history."""
import hashlib
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
import urllib.error
import urllib.request
from pathlib import Path

import psycopg
import pytest
import uvicorn
from currency_legacy_fixture import KEYS
from currency_legacy_oracle import assert_inventory_unchanged, canonical, snapshot_legacy_facts
from currency_upgrade_adversarial import (
    assert_dependency_preserved,
    assert_drift_refusal,
    assert_no_false_completion,
    assert_outage_preserved,
    assert_refusal_unchanged,
    assert_target_refusal,
    assert_unknown_values_preserved,
    qualify_outage_then_retry,
    run_adversarial,
    run_drift_matrix,
    run_pg_hazards,
)
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.rows import dict_row
from test_acc_currency_separate_totals import by_currency

from apps.api.app import create_app
from packages.domains.finance.pipelines.account_transaction_service import AccountTransactionService
from packages.pipelines.reporting_service import ReportingAccessMode, ReportingService
from packages.pipelines.transformation_service import TransformationService
from packages.storage.duckdb_store import DuckDBStore
from packages.storage.postgres_reporting import PostgresReportingStore
from packages.storage.run_metadata import RunMetadataRepository


def history_unavailable(body):
    assert body["as_of_status"] == "legacy_denomination_unavailable", body
    assert body["rows"] == [], body
    assert body["snapshot"] is not None, body
    assert body["snapshot"]["reference_month"] == "2026-01", body
    assert body["snapshot"]["run_id"] == "legacy-january", body
    assert body["snapshot"]["row_count"] == 1, body


def test_history_oracle_distinguishes_unavailable_from_valid_empty_and_no_history():
    good = {"as_of_status": "legacy_denomination_unavailable", "rows": [],
            "snapshot": {"reference_month": "2026-01", "run_id": "legacy-january", "row_count": 1}}
    history_unavailable(good)
    for bad in ({**good, "as_of_status": "no_history"}, {**good, "as_of_status": "snapshot"},
                {**good, "snapshot": None}, {**good, "rows": [{"cashflow_net": 250}]}):
        with pytest.raises(AssertionError):
            history_unavailable(bad)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pg_dump(dsn, schema):
    executable = os.environ["CURRENCY_LEGACY_PG_DUMP"]
    result = subprocess.run([executable, "--dbname", dsn, "--schema", schema,
                             "--inserts", "--column-inserts"], capture_output=True, check=True, timeout=60).stdout
    # pg_dump's session-specific restrict token is not database state.
    return re.sub(rb"(?m)^\\(?:un)?restrict [^\r\n]*\r?\n", b"", result)


def snapshot_rows_duck(store):
    return store.fetchall_dicts("SELECT publication_key, reference_month, captured_at, run_id, row_count, rows_json FROM reporting_publication_snapshot ORDER BY publication_key, reference_month")


def snapshot_rows_pg(dsn, schema):
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        query = sql.SQL("SELECT publication_key, reference_month, captured_at, run_id, row_count, rows_json FROM {}.reporting_publication_snapshot ORDER BY publication_key, reference_month").format(sql.Identifier(schema))
        return conn.execute(query).fetchall()


def assert_legacy_publications_present(dsn, manifest):
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        for table, original in manifest["postgres_rows"].items():
            query = sql.SQL("SELECT * FROM {}.{}").format(sql.Identifier(manifest["postgres_schema"]), sql.Identifier(table))
            observed = [{name: canonical(value) for name, value in row.items()} for row in conn.execute(query).fetchall()]
            observed.sort(key=lambda row: json.dumps(row, sort_keys=True))
            assert observed == original, table
        for table, original in manifest["postgres_schemas"].items():
            rows = conn.execute("SELECT column_name, data_type, is_nullable, ordinal_position FROM information_schema.columns WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position", (manifest["postgres_schema"], table)).fetchall()
            observed = [[row["column_name"], row["data_type"], row["is_nullable"], row["ordinal_position"]] for row in rows]
            assert observed == original, table


def assert_snapshot_rows_preserved(original, observed):
    for old in original:
        matches = [row for row in observed if row["publication_key"] == old["publication_key"] and row["reference_month"] == old["reference_month"]]
        assert matches == [old], (old, matches)


def test_snapshot_oracle_rejects_changed_missing_and_duplicate_old_bytes():
    old = {"publication_key": "mart_household_overview", "reference_month": "2026-01", "rows_json": '[{"cashflow_net":"250"}]'}
    later = {"publication_key": "mart_household_overview", "reference_month": "2026-02", "rows_json": "[]"}
    assert_snapshot_rows_preserved([old], [old, later])
    for bad in ([], [{**old, "rows_json": "[]"}], [old, old]):
        with pytest.raises(AssertionError):
            assert_snapshot_rows_preserved([old], bad)


def assert_original_snapshots(store, dsn, manifest):
    for observed, original in ((snapshot_rows_duck(store), manifest["legacy_snapshots"]["duckdb"]),
                               (snapshot_rows_pg(dsn, manifest["postgres_schema"]), manifest["legacy_snapshots"]["postgres"])):
        assert_snapshot_rows_preserved(original, observed)


def command(args, env, *, require_success=True):
    result = subprocess.run([sys.executable, "-m", "apps.worker.main", "upgrade-reporting", *args],
                            env=env, capture_output=True, text=True, timeout=180)
    if require_success:
        assert result.returncode == 0, (args, result.returncode, result.stdout, result.stderr)
    return result


def verify_historical_ui(app, ui_report, *, api_port, web_port):
    for port in (api_port, web_port):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", port))
    api_url = f"http://127.0.0.1:{api_port}"
    web_url = f"http://127.0.0.1:{web_port}"
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=api_port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    env = os.environ.copy()
    env.update({"HOMELAB_ANALYTICS_API_BASE_URL": api_url, "CURRENCY_LEGACY_API_URL": api_url,
                "CURRENCY_LEGACY_WEB_URL": web_url, "PLAYWRIGHT_JSON_OUTPUT_FILE": str(ui_report)})
    frontend = Path.cwd() / "apps/web/frontend"
    node = shutil.which("node")
    assert node, "Node is required for the legacy history consumer check"
    web = None
    thread.start()
    try:
        web = subprocess.Popen([node, str(frontend / "node_modules/next/dist/bin/next"), "dev", "-H", "127.0.0.1", "-p", str(web_port)],
                               cwd=frontend, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            assert web.poll() is None, "candidate frontend exited during startup"
            try:
                with urllib.request.urlopen(api_url + "/reports/household-overview?as_of=2026-01", timeout=2) as response:
                    assert response.status == 200
                with urllib.request.urlopen(web_url + "/?asof=2026-01", timeout=2) as response:
                    assert response.status == 200
                break
            except (OSError, urllib.error.URLError):
                time.sleep(.2)
        else:
            pytest.fail("legacy API and frontend did not become ready")
        result = subprocess.run([node, str(frontend / "node_modules/@playwright/test/cli.js"), "test",
                                 "playwright/currency-legacy-history.spec.js", "--project=chromium", "--reporter=json",
                                 "--grep", "past household view presents unavailable legacy denomination"],
                                cwd=frontend, env=env, capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, (result.stdout, result.stderr)
        report = json.loads(ui_report.read_text())
        assert not report["errors"] and report["stats"]["expected"] == 1
        assert all(report["stats"][name] == 0 for name in ("skipped", "unexpected", "flaky"))
        specs = [spec for suite in report["suites"] for spec in suite.get("specs", [])]
        assert len(specs) == 1 and specs[0]["title"] == "past household view presents unavailable legacy denomination"
        assert len(specs[0]["tests"]) == 1 and len(specs[0]["tests"][0]["results"]) == 1 and specs[0]["tests"][0]["results"][0]["status"] == "passed"
    finally:
        server.should_exit = True
        if web is not None:
            try:
                os.killpg(web.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                web.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(web.pid, signal.SIGKILL)
                web.wait(timeout=5)
        thread.join(timeout=10)
        assert not thread.is_alive(), "legacy API server did not stop"


def test_legacy_upgrade_preserves_facts_snapshots_and_published_currency(tmp_path):
    manifest = json.loads(Path(os.environ["CURRENCY_LEGACY_MANIFEST"]).read_text())
    warehouse = Path(os.environ["CURRENCY_LEGACY_WAREHOUSE"])
    dsn = os.environ["CURRENCY_LEGACY_POSTGRES_DSN"]
    schema = manifest["postgres_schema"]
    assert manifest["kind"] == "hla-currency-legacy-fixture/v2"
    assert digest(warehouse) == manifest["warehouse_sha256"]
    env = os.environ.copy()
    env.update({"HOMELAB_ANALYTICS_ANALYTICS_DATABASE_PATH": str(warehouse),
                "HOMELAB_ANALYTICS_REPORTING_BACKEND": "postgres",
                "HOMELAB_ANALYTICS_REPORTING_POSTGRES_DSN": dsn,
                "HOMELAB_ANALYTICS_REPORTING_SCHEMA": schema})
    env.pop("HOMELAB_ANALYTICS_POSTGRES_DSN", None)
    before = DuckDBStore.open(str(warehouse), read_only=True)
    try:
        assert_inventory_unchanged(manifest["facts"], snapshot_legacy_facts(before, manifest["facts"]))
        assert_original_snapshots(before, dsn, manifest)
    finally:
        before.close()
    assert_legacy_publications_present(dsn, manifest)
    before_pg = pg_dump(dsn, schema)
    assert pg_dump(dsn, schema) == before_pg, "pg_dump is not stable enough to prove --check is read-only"
    # Check is explicitly read-only, including the whole existing reporting schema.
    check = command(["--check"], env, require_success=False)
    assert digest(warehouse) == manifest["warehouse_sha256"]
    assert pg_dump(dsn, schema) == before_pg
    assert check.returncode == 0, ("--check", check.returncode, check.stdout, check.stderr)
    ui_report = Path(os.environ["CURRENCY_LEGACY_UI_REPORT"])
    first_report = Path(str(ui_report) + ".first")
    assert not first_report.exists() and not ui_report.exists()

    def run_upgrade():
        result = command([], env)
        completion = json.loads(result.stdout)
        assert isinstance(completion, dict) and completion, completion

    ports = {
        1: (int(os.environ["CURRENCY_LEGACY_API_PORT"]), int(os.environ["CURRENCY_LEGACY_WEB_PORT"])),
        2: (int(os.environ["CURRENCY_LEGACY_RETRY_API_PORT"]), int(os.environ["CURRENCY_LEGACY_RETRY_WEB_PORT"])),
    }
    assert len(set(ports[1] + ports[2])) == 4, "first and retry browser fixtures require distinct listeners"

    def verify_upgrade(attempt):
        api_port, web_port = ports[attempt]
        verify_completed_upgrade(manifest, warehouse, dsn, schema, tmp_path,
                                 first_report if attempt == 1 else ui_report,
                                 clear_warehouse=attempt == 2, api_port=api_port, web_port=web_port)

    qualify_first_then_retry(run_upgrade, verify_upgrade)
    run_adversarial(env, command, digest, pg_dump, assert_original_snapshots, by_currency, assert_legacy_publications_present)
    run_drift_matrix(env, command, digest, pg_dump, assert_original_snapshots, by_currency, assert_legacy_publications_present)
    run_pg_hazards(env, command, digest, pg_dump, assert_original_snapshots, assert_legacy_publications_present)


def qualify_first_then_retry(run_upgrade, verify_upgrade):
    for attempt in (1, 2):
        run_upgrade()
        verify_upgrade(attempt)


def test_first_completed_upgrade_is_checked_before_retry():
    events = []
    state = {"rows": []}
    complete_rows = [{"currency": "EUR", "net": 170}, {"currency": "USD", "net": 80}]

    def verify(attempt):
        events.append(f"verify-{attempt}")
        by_currency(state["rows"], "net", {"EUR": 170, "USD": 80})

    def complete():
        events.append("run")
        state["rows"] = complete_rows

    qualify_first_then_retry(complete, verify)
    assert events == ["run", "verify-1", "run", "verify-2"]
    events.clear()

    def partial_then_repairs():
        events.append("run")
        state["rows"] = complete_rows[:1] if events.count("run") == 1 else complete_rows

    with pytest.raises(AssertionError):
        qualify_first_then_retry(partial_then_repairs, verify)
    assert events == ["run", "verify-1"]
    # Prove this simulated second run would have hidden the first bad result.
    partial_then_repairs()
    verify(2)


def test_adversarial_refusal_oracle_rejects_false_success_and_mutation():
    assert_refusal_unchanged(1, ("warehouse", "postgres"), ("warehouse", "postgres"))
    unchanged = ("warehouse", "postgres")
    drift = subprocess.CompletedProcess([], 2, '{"status":"refused","refusals":["unknown columns in mart_household_overview"]}', "")
    assert_drift_refusal(drift, "mart_household_overview", unchanged, unchanged)
    with pytest.raises(AssertionError):
        assert_target_refusal(drift, "mart_household_overview", unchanged, unchanged, "trigger")
    for bad_drift in (
        subprocess.CompletedProcess([], 2, "", "command not found"),
        subprocess.CompletedProcess([], 2, "", "unknown columns in mart_household_overview_suffix"),
        subprocess.CompletedProcess([], 2, '{"status":"refused","states":{"mart_household_overview":"legacy"},"refusals":["schema unknown on mart_monthly_cashflow"]}', ""),
        subprocess.CompletedProcess([], 2, "", "unknown columns in mart_monthly_cashflow"),
        subprocess.CompletedProcess([], 2, '{"status":"success"}', drift.stderr),
        subprocess.CompletedProcess([], 0, drift.stdout, drift.stderr),
    ):
        with pytest.raises(AssertionError):
            assert_drift_refusal(bad_drift, "mart_household_overview", unchanged, unchanged)
    assert_unknown_values_preserved(["foreign sentinel"], ["foreign sentinel"])
    for changed in ([], [None], ["other"], ["foreign sentinel", "foreign sentinel"]):
        with pytest.raises(AssertionError):
            assert_unknown_values_preserved(["foreign sentinel"], changed)
    assert_dependency_preserved("original view", "original view", 1)
    with pytest.raises(AssertionError):
        assert_dependency_preserved("original view", "different view", 1)
    with pytest.raises(AssertionError):
        assert_dependency_preserved("original view", "original view", 0)
    assert_no_false_completion('{"status":"error"}')
    with pytest.raises(AssertionError):
        assert_no_false_completion('{"status":"success"}')
    for code, after in ((0, ("warehouse", "postgres")), (1, ("changed", "postgres")), (1, ("warehouse", "changed"))):
        with pytest.raises(AssertionError):
            assert_refusal_unchanged(code, ("warehouse", "postgres"), after)

    original = {"acceptance_foreign_keep": ["sentinel"]}
    events = []
    failure = subprocess.CompletedProcess([], 2, '{"status":"incomplete"}', "")

    def verify_untouched():
        events.append("verify")
        assert_outage_preserved(original, original, b"published", b"published")

    def retry():
        events.append("retry")

    qualify_outage_then_retry(lambda: failure, verify_untouched, retry)
    assert events == ["verify", "retry"]
    for mutated, published in (({}, b"published"), (original, b"mutated")):
        events.clear()
        with pytest.raises(AssertionError):
            qualify_outage_then_retry(
                lambda: failure,
                lambda: assert_outage_preserved(original, mutated, b"published", published),
                retry,
            )
        assert events == [], "retry could mask a damaging first attempt"


def verify_completed_upgrade(manifest, warehouse, dsn, schema, tmp_path, ui_report, *, clear_warehouse, api_port, web_port):
    # Verify this completed command's persistent outputs before any app
    # constructor can bootstrap or repair schema.
    pre_app = DuckDBStore.open(str(warehouse), read_only=True)
    try:
        assert_inventory_unchanged(manifest["facts"], snapshot_legacy_facts(pre_app, manifest["facts"]))
        assert_original_snapshots(pre_app, dsn, manifest)
        warehouse_rows = pre_app.fetchall_dicts("SELECT * FROM mart_monthly_cashflow WHERE booking_month = '2026-01'")
        by_currency(warehouse_rows, "net", {"EUR": 170, "USD": 80})
    finally:
        pre_app.close()
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        query = sql.SQL("SELECT * FROM {}.mart_monthly_cashflow WHERE booking_month = %s").format(sql.Identifier(schema))
        published_rows = conn.execute(query, ("2026-01",)).fetchall()
        by_currency(published_rows, "net", {"EUR": 170, "USD": 80})
    store = DuckDBStore.open(str(warehouse))
    try:
        assert_inventory_unchanged(manifest["facts"], snapshot_legacy_facts(store, manifest["facts"]))
        assert_original_snapshots(store, dsn, manifest)
        transformation = TransformationService(store)
        reporting = ReportingService(transformation, publication_store=PostgresReportingStore(dsn, schema=schema),
                                     access_mode=ReportingAccessMode.PUBLISHED)
        service = AccountTransactionService(landing_root=tmp_path / "landing", metadata_repository=RunMetadataRepository(tmp_path / "runs.db"))
        app = create_app(service, transformation_service=transformation, reporting_service=reporting)
        with TestClient(app) as client:
            def verify_current():
                response = client.get("/reports/monthly-cashflow", params={"from_month": "2026-01", "to_month": "2026-01"})
                assert response.status_code == 200, response.text
                by_currency(response.json()["rows"], "net", {"EUR": 170, "USD": 80})
                utility = client.get("/reports/utility-cost-trend")
                assert utility.status_code == 200, utility.text
                by_currency([r for r in utility.json()["rows"] if r["billing_month"] == "2026-01"], "total_cost", {"EUR": 200, "USD": 100})
                historical = client.get("/reports/household-overview", params={"as_of": "2026-01"})
                assert historical.status_code == 200, historical.text
                history_unavailable(historical.json())
                missing = client.get("/reports/household-overview", params={"as_of": "2025-12"})
                assert missing.status_code == 200 and missing.json()["as_of_status"] == "no_history" and missing.json()["rows"] == []
                empty = client.get("/reports/subscription-summary", params={"as_of": "2026-01"})
                assert empty.status_code == 200 and empty.json()["as_of_status"] == "snapshot" and empty.json()["rows"] == [] and empty.json()["snapshot"]["row_count"] == 0
            verify_current()
            if clear_warehouse:
                # Isolation check after the retry; never repair candidate output.
                for key in KEYS:
                    store.execute(f'DELETE FROM "{key}"')
                    assert store.fetchall(f'SELECT COUNT(*) FROM "{key}"')[0][0] == 0
                verify_current()
            assert_inventory_unchanged(manifest["facts"], snapshot_legacy_facts(store, manifest["facts"]))
            assert_original_snapshots(store, dsn, manifest)
        verify_historical_ui(app, ui_report, api_port=api_port, web_port=web_port)
        assert_inventory_unchanged(manifest["facts"], snapshot_legacy_facts(store, manifest["facts"]))
        assert_original_snapshots(store, dsn, manifest)
    finally:
        store.close()
