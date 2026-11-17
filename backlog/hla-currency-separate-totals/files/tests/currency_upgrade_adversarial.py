"""Private legacy upgrade controls; run only after a successful qualification."""
import json
import os
from pathlib import Path
from uuid import uuid4

import psycopg
from currency_legacy_oracle import assert_inventory_unchanged, snapshot_legacy_facts
from psycopg import sql
from psycopg.conninfo import make_conninfo

from packages.storage.duckdb_store import DuckDBStore


def facts_and_history(warehouse, dsn, manifest, snapshots):
    store = DuckDBStore.open(str(warehouse), read_only=True)
    try:
        assert_inventory_unchanged(manifest["facts"], snapshot_legacy_facts(store, manifest["facts"]))
        snapshots(store, dsn, manifest)
    finally:
        store.close()


def completed_output(warehouse, dsn, manifest, snapshots, by_currency):
    facts_and_history(warehouse, dsn, manifest, snapshots)
    store = DuckDBStore.open(str(warehouse), read_only=True)
    try:
        rows = store.fetchall_dicts("SELECT * FROM mart_monthly_cashflow WHERE booking_month = '2026-01'")
        by_currency(rows, "net", {"EUR": 170, "USD": 80})
    finally:
        store.close()
    with psycopg.connect(dsn, row_factory=psycopg.rows.dict_row) as conn:
        query = sql.SQL("SELECT * FROM {}.mart_monthly_cashflow WHERE booking_month = %s").format(sql.Identifier(manifest["postgres_schema"]))
        by_currency(conn.execute(query, ("2026-01",)).fetchall(), "net", {"EUR": 170, "USD": 80})


def assert_no_false_completion(stdout):
    try:
        body = json.loads(stdout)
    except (ValueError, TypeError):
        return
    if isinstance(body, dict):
        assert body.get("success") is not True and body.get("status") not in ("success", "completed", "complete"), body


def assert_refusal_unchanged(returncode, before, after):
    assert returncode != 0, "refusal returned success"
    assert before == after, "refusal changed a persisted store"


def assert_dependency_preserved(before, after, granted):
    assert after == before, "dependent view changed"
    assert granted == 1, "original PUBLIC SELECT grant lost"


def run_adversarial(base_env, command, digest, pg_dump, snapshots, by_currency, legacy_publications):
    """Each scenario owns its separate 82 warehouse and PostgreSQL schema."""
    dsn = base_env["HOMELAB_ANALYTICS_REPORTING_POSTGRES_DSN"]
    for label in ("drift", "dependency", "outage"):
        warehouse = Path(os.environ[f"CURRENCY_LEGACY_{label.upper()}_WAREHOUSE"])
        manifest = json.loads(Path(os.environ[f"CURRENCY_LEGACY_{label.upper()}_MANIFEST"]).read_text())
        schema = manifest["postgres_schema"]
        env = dict(base_env, HOMELAB_ANALYTICS_ANALYTICS_DATABASE_PATH=str(warehouse), HOMELAB_ANALYTICS_REPORTING_SCHEMA=schema)
        facts_and_history(warehouse, dsn, manifest, snapshots)
        legacy_publications(dsn, manifest)
        if label == "drift":
            with psycopg.connect(dsn, autocommit=True) as conn:
                conn.execute(sql.SQL("ALTER TABLE {}.mart_monthly_cashflow ADD COLUMN acceptance_unknown_drift TEXT").format(sql.Identifier(schema)))
            before_duck, before_pg = digest(warehouse), pg_dump(dsn, schema)
            for args in (["--check"], []):
                result = command(args, env, require_success=False)
                assert_no_false_completion(result.stdout)
                assert_refusal_unchanged(result.returncode, (before_duck, before_pg), (digest(warehouse), pg_dump(dsn, schema)))
            facts_and_history(warehouse, dsn, manifest, snapshots)
        elif label == "dependency":
            with psycopg.connect(dsn, autocommit=True) as conn:
                conn.execute(sql.SQL("CREATE VIEW {}.acceptance_dependent_view AS SELECT booking_month FROM {}.mart_monthly_cashflow").format(sql.Identifier(schema), sql.Identifier(schema)))
                conn.execute(sql.SQL("GRANT SELECT ON {}.mart_monthly_cashflow TO PUBLIC").format(sql.Identifier(schema)))
                view_definition = conn.execute("SELECT pg_get_viewdef(%s::regclass, true)", (f"{schema}.acceptance_dependent_view",)).fetchone()[0]
            before_duck, before_pg = digest(warehouse), pg_dump(dsn, schema)
            command(["--check"], env, require_success=False)
            assert digest(warehouse) == before_duck and pg_dump(dsn, schema) == before_pg
            result = command([], env, require_success=False)
            if result.returncode:
                assert_no_false_completion(result.stdout)
                assert digest(warehouse) == before_duck and pg_dump(dsn, schema) == before_pg
                facts_and_history(warehouse, dsn, manifest, snapshots)
            else:
                completion = json.loads(result.stdout)
                assert isinstance(completion, dict) and completion
                with psycopg.connect(dsn) as conn:
                    conn.execute(sql.SQL("SELECT count(*) FROM {}.acceptance_dependent_view").format(sql.Identifier(schema))).fetchone()
                    observed_view = conn.execute("SELECT pg_get_viewdef(%s::regclass, true)", (f"{schema}.acceptance_dependent_view",)).fetchone()[0]
                    granted = conn.execute("SELECT count(*) FROM information_schema.table_privileges WHERE table_schema = %s AND table_name = 'mart_monthly_cashflow' AND grantee = 'PUBLIC' AND privilege_type = 'SELECT'", (schema,)).fetchone()[0]
                    assert_dependency_preserved(view_definition, observed_view, granted)
                completed_output(warehouse, dsn, manifest, snapshots, by_currency)
        else:
            bad_dsn = make_conninfo(dsn, host=f"/tmp/currency-unavailable-{uuid4().hex}", hostaddr="", connect_timeout=2)
            inaccessible = dict(env, HOMELAB_ANALYTICS_REPORTING_POSTGRES_DSN=bad_dsn)
            before_duck, before_pg = digest(warehouse), pg_dump(dsn, schema)
            check = command(["--check"], inaccessible, require_success=False)
            assert check.returncode != 0
            assert digest(warehouse) == before_duck and pg_dump(dsn, schema) == before_pg
            result = command([], inaccessible, require_success=False)
            assert result.returncode != 0, (label, result.stdout, result.stderr)
            assert_no_false_completion(result.stdout)
            facts_and_history(warehouse, dsn, manifest, snapshots)
            retry = command([], env)
            completion = json.loads(retry.stdout)
            assert isinstance(completion, dict) and completion
            completed_output(warehouse, dsn, manifest, snapshots, by_currency)
