"""Private legacy upgrade controls; run only after a successful qualification."""
import json
import os
import re
from pathlib import Path
from uuid import uuid4

import psycopg
from currency_drift_inventory import MARTS, PG_HAZARD_TARGET, PG_HAZARDS
from currency_legacy_oracle import assert_inventory_unchanged, canonical, snapshot_legacy_facts
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
        assert body.get("success") is not True and body.get("status") not in ("success", "completed", "complete", "check_ok"), body


def assert_refusal_unchanged(returncode, before, after):
    assert returncode != 0, "refusal returned success"
    assert before == after, "refusal changed a persisted store"


def assert_target_refusal(result, relation, before, after, reason):
    assert result.returncode != 0, (relation, "refusal returned success", result.stdout, result.stderr)
    assert_refusal_unchanged(result.returncode, before, after)
    assert_no_false_completion(result.stdout)
    try:
        body = json.loads(result.stdout)
    except ValueError:
        body = None
    if isinstance(body, dict):
        diagnostic = json.dumps({key: body.get(key) for key in ("refusals", "error")})
    else:
        diagnostic = result.stdout + "\n" + result.stderr
    diagnostic = diagnostic.casefold()
    name = rf"(?<![a-z0-9_]){re.escape(relation.casefold())}(?![a-z0-9_])"
    assert re.search(name, diagnostic), "refusal did not identify the affected relation"
    assert re.search(reason, diagnostic), "refusal did not identify the injected hazard"


def assert_drift_refusal(result, relation, before, after):
    assert_target_refusal(result, relation, before, after, "column|schema")


def assert_dependency_preserved(before, after, granted):
    assert after == before, "dependent view changed"
    assert granted == 1, "original PUBLIC SELECT grant lost"


def assert_unknown_values_preserved(before, after):
    assert before == after and before, "unknown persisted values were lost or changed"


def run_adversarial(base_env, command, digest, pg_dump, snapshots, by_currency, legacy_publications):
    """Each scenario owns its separate 82 warehouse and PostgreSQL schema."""
    for label in ("warehouse_drift", "drift", "dependency", "outage"):
        run_adversarial_case(label, base_env, command, digest, pg_dump, snapshots, by_currency, legacy_publications)


def run_adversarial_case(label, base_env, command, digest, pg_dump, snapshots, by_currency, legacy_publications):
    dsn = base_env["HOMELAB_ANALYTICS_REPORTING_POSTGRES_DSN"]
    warehouse = Path(os.environ[f"CURRENCY_LEGACY_{label.upper()}_WAREHOUSE"])
    manifest = json.loads(Path(os.environ[f"CURRENCY_LEGACY_{label.upper()}_MANIFEST"]).read_text())
    schema = manifest["postgres_schema"]
    env = dict(base_env, HOMELAB_ANALYTICS_ANALYTICS_DATABASE_PATH=str(warehouse), HOMELAB_ANALYTICS_REPORTING_SCHEMA=schema)
    facts_and_history(warehouse, dsn, manifest, snapshots)
    legacy_publications(dsn, manifest)
    if label == "warehouse_drift":
        probe_warehouse_drift("mart_household_overview", warehouse, env, manifest, command, digest, pg_dump, snapshots, by_currency)
    elif label == "drift":
        for relation in ("mart_monthly_cashflow", "mart_household_overview"):
            probe_postgres_drift(relation, warehouse, env, manifest, command, digest, pg_dump, snapshots)
            legacy_publications(dsn, manifest)
    elif label == "dependency":
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE VIEW {}.acceptance_dependent_view AS SELECT booking_month FROM {}.mart_monthly_cashflow").format(sql.Identifier(schema), sql.Identifier(schema)))
            conn.execute(sql.SQL("GRANT SELECT ON {}.mart_monthly_cashflow TO PUBLIC").format(sql.Identifier(schema)))
            view_definition = conn.execute("SELECT pg_get_viewdef(%s::regclass, true)", (f"{schema}.acceptance_dependent_view",)).fetchone()[0]
        before_duck, before_pg = digest(warehouse), pg_dump(dsn, schema)
        check = command(["--check"], env, require_success=False)
        if check.returncode:
            assert_no_false_completion(check.stdout)
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
        owned = DuckDBStore.open(str(warehouse))
        try:
            owned.execute("CREATE TABLE acceptance_foreign_keep (note VARCHAR NOT NULL)")
            owned.execute("INSERT INTO acceptance_foreign_keep VALUES ('original foreign sentinel')")
        finally:
            owned.close()
        before_duck, before_pg = digest(warehouse), pg_dump(dsn, schema)
        original_unrelated = warehouse_unrelated_inventory(warehouse)
        assert "acceptance_foreign_keep" in original_unrelated
        check = command(["--check"], inaccessible, require_success=False)
        assert check.returncode != 0
        assert_no_false_completion(check.stdout)
        assert digest(warehouse) == before_duck and pg_dump(dsn, schema) == before_pg

        def verify_preserved():
            facts_and_history(warehouse, dsn, manifest, snapshots)
            assert_outage_preserved(original_unrelated, warehouse_unrelated_inventory(warehouse),
                                    before_pg, pg_dump(dsn, schema))

        def retry():
            result = command([], env)
            completion = json.loads(result.stdout)
            assert isinstance(completion, dict) and completion
            completed_output(warehouse, dsn, manifest, snapshots, by_currency)
            assert original_unrelated == warehouse_unrelated_inventory(warehouse)

        qualify_outage_then_retry(
            lambda: command([], inaccessible, require_success=False), verify_preserved, retry,
        )


def warehouse_unrelated_inventory(warehouse):
    # Derived mart rebuilds and the maintenance marker can be partially applied.
    # Original snapshot rows and facts are independently checked even if their
    # relations are present in this inventory.
    maintenance = set(MARTS) | {"reporting_publication_snapshot", "schema_migrations"}
    store = DuckDBStore.open(str(warehouse), read_only=True)
    try:
        names = store.fetchall(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main' ORDER BY table_name"
        )
        inventory = {}
        for (name,) in names:
            if name in maintenance:
                continue
            quoted = '"' + name.replace('"', '""') + '"'
            columns = store.fetchall(f"PRAGMA table_info({quoted})")
            rows = [[canonical(value) for value in row] for row in store.fetchall(f"SELECT * FROM {quoted}")]
            inventory[name] = (columns, sorted(rows, key=lambda row: json.dumps(row, sort_keys=True)))
        return inventory
    finally:
        store.close()


def assert_outage_preserved(original_unrelated, observed_unrelated, original_pg, observed_pg):
    assert observed_unrelated == original_unrelated, "outage changed state outside reporting maintenance"
    assert observed_pg == original_pg, "outage changed the unreachable publication store"


def qualify_outage_then_retry(fail, verify_before_retry, retry):
    result = fail()
    assert result.returncode != 0, (result.stdout, result.stderr)
    assert_no_false_completion(result.stdout)
    verify_before_retry()
    retry()



def seed_value(data_type):
    """A typed value for a disposable derived row when a seeded mart is empty."""
    base_type = data_type.casefold().split("(")[0]
    return {
        "varchar": "acceptance",
        "character varying": "acceptance",
        "text": "acceptance",
        "date": "2026-01-01",
        "numeric": 0,
        "decimal": 0,
        "integer": 0,
        "bigint": 0,
        "boolean": False,
    }[base_type]


SENTINEL = "synthetic preserved sentinel"
COLUMN = "acceptance_unknown_drift"


def probe_warehouse_drift(relation, warehouse, env, manifest, command, digest, pg_dump, snapshots, by_currency):
    dsn = env["HOMELAB_ANALYTICS_REPORTING_POSTGRES_DSN"]
    schema = manifest["postgres_schema"]
    owned = DuckDBStore.open(str(warehouse))
    try:
        columns = owned.fetchall(f"PRAGMA table_info('{relation}')")
        assert columns, relation
        owned.execute(f'ALTER TABLE "{relation}" ADD COLUMN {COLUMN} VARCHAR')
        count = owned.fetchall(f'SELECT count(*) FROM "{relation}"')[0][0]
        if count:
            owned.execute(f'UPDATE "{relation}" SET {COLUMN} = ?', [SENTINEL])
        else:
            values = [seed_value(column[2]) for column in columns] + [SENTINEL]
            placeholders = ", ".join("?" for _ in values)
            owned.execute(f'INSERT INTO "{relation}" VALUES ({placeholders})', values)
        original = sorted(row[0] for row in owned.fetchall(f'SELECT {COLUMN} FROM "{relation}"'))
        assert original and set(original) == {SENTINEL}, relation
    finally:
        owned.close()
    before = (digest(warehouse), pg_dump(dsn, schema))
    check = command(["--check"], env, require_success=False)
    checked = (digest(warehouse), pg_dump(dsn, schema))
    assert checked == before, (relation, "--check changed a store")
    if check.returncode:
        assert_drift_refusal(check, relation, before, checked)
    result = command([], env, require_success=False)
    if check.returncode:
        assert_drift_refusal(result, relation, before, (digest(warehouse), pg_dump(dsn, schema)))
        facts_and_history(warehouse, dsn, manifest, snapshots)
        return
    completion = json.loads(result.stdout) if result.returncode == 0 else None
    assert isinstance(completion, dict) and completion, (relation, result.returncode, result.stdout, result.stderr)
    observed_store = DuckDBStore.open(str(warehouse), read_only=True)
    try:
        observed_columns = {row[1] for row in observed_store.fetchall(f"PRAGMA table_info('{relation}')")}
        assert COLUMN in observed_columns, (relation, "unknown column was removed")
        observed = sorted(row[0] for row in observed_store.fetchall(
            f'SELECT {COLUMN} FROM "{relation}" WHERE {COLUMN} IS NOT NULL'
        ))
        assert_unknown_values_preserved(original, observed)
    finally:
        observed_store.close()
    completed_output(warehouse, dsn, manifest, snapshots, by_currency)


def probe_postgres_drift(relation, warehouse, env, manifest, command, digest, pg_dump, snapshots):
    dsn = env["HOMELAB_ANALYTICS_REPORTING_POSTGRES_DSN"]
    schema = manifest["postgres_schema"]
    table, column = sql.Identifier(schema, relation), sql.Identifier(COLUMN)
    with psycopg.connect(dsn) as conn:
        count = conn.execute(sql.SQL("SELECT count(*) FROM {}").format(table)).fetchone()[0]
        columns = conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
            (schema, relation),
        ).fetchall()
        assert columns, relation
        conn.execute(sql.SQL("ALTER TABLE {} ADD COLUMN {} TEXT").format(table, column))
        if count:
            result = conn.execute(sql.SQL("UPDATE {} SET {} = %s").format(table, column), (SENTINEL,))
            assert result.rowcount == count
        else:
            values = [seed_value(data_type) for _, data_type in columns] + [SENTINEL]
            names = sql.SQL(", ").join([sql.Identifier(name) for name, _ in columns] + [column])
            placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in values)
            conn.execute(sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(table, names, placeholders), values)
        populated = conn.execute(sql.SQL("SELECT count(*) FROM {} WHERE {} = %s").format(table, column), (SENTINEL,)).fetchone()[0]
        assert populated == max(count, 1), relation
    before = (digest(warehouse), pg_dump(dsn, schema))
    for args in (["--check"], []):
        result = command(args, env, require_success=False)
        assert_drift_refusal(result, relation, before, (digest(warehouse), pg_dump(dsn, schema)))
    facts_and_history(warehouse, dsn, manifest, snapshots)
    with psycopg.connect(dsn) as conn:
        if not count:
            removed = conn.execute(sql.SQL("DELETE FROM {} WHERE {} = %s").format(table, column), (SENTINEL,))
            assert removed.rowcount == 1
        conn.execute(sql.SQL("ALTER TABLE {} DROP COLUMN {}").format(table, column))


def run_drift_matrix(base_env, command, digest, pg_dump, snapshots, by_currency, legacy_publications):
    directory = Path(os.environ["CURRENCY_LEGACY_DRIFT_MATRIX"])
    dsn = base_env["HOMELAB_ANALYTICS_REPORTING_POSTGRES_DSN"]
    for relation in MARTS:
        warehouse = directory / f"{relation}.duckdb"
        manifest = json.loads((directory / f"{relation}.json").read_text())
        assert manifest["drift_relation"] == relation
        assert digest(warehouse) == manifest["warehouse_sha256"]
        env = dict(base_env, HOMELAB_ANALYTICS_ANALYTICS_DATABASE_PATH=str(warehouse),
                   HOMELAB_ANALYTICS_REPORTING_SCHEMA=manifest["postgres_schema"])
        facts_and_history(warehouse, dsn, manifest, snapshots)
        legacy_publications(dsn, manifest)
        probe_postgres_drift(relation, warehouse, env, manifest, command, digest, pg_dump, snapshots)
        legacy_publications(dsn, manifest)
        probe_warehouse_drift(relation, warehouse, env, manifest, command, digest, pg_dump, snapshots, by_currency)



def create_pg_hazard(conn, schema, hazard, role):
    table = sql.Identifier(schema, PG_HAZARD_TARGET)
    if hazard == "trigger":
        function = sql.Identifier(schema, "acceptance_republish_trigger")
        conn.execute(sql.SQL(
            "CREATE FUNCTION {}() RETURNS trigger LANGUAGE plpgsql "
            "AS $$BEGIN RAISE EXCEPTION 'acceptance trigger fired'; END;$$"
        ).format(function))
        conn.execute(sql.SQL(
            "CREATE TRIGGER acceptance_republish_guard BEFORE TRUNCATE ON {} "
            "FOR EACH STATEMENT EXECUTE FUNCTION {}()"
        ).format(table, function))
        definition = conn.execute(
            "SELECT pg_get_triggerdef(oid) FROM pg_trigger "
            "WHERE tgrelid = %s::regclass AND tgname = 'acceptance_republish_guard'",
            (table.as_string(conn),),
        ).fetchone()
        assert definition and "BEFORE TRUNCATE" in definition[0], definition
        return "trigger"
    if hazard == "row-security":
        conn.execute(sql.SQL("ALTER TABLE {} ENABLE ROW LEVEL SECURITY").format(table))
        conn.execute(sql.SQL("CREATE POLICY acceptance_republish_policy ON {} USING (false)").format(table))
        assert conn.execute(
            "SELECT c.relrowsecurity FROM pg_class c JOIN pg_policy p ON p.polrelid = c.oid "
            "WHERE c.oid = %s::regclass AND p.polname = 'acceptance_republish_policy'",
            (table.as_string(conn),),
        ).fetchone() == (True,)
        return r"row[- ]level[- ]security|policy|\brls\b"
    if hazard == "foreign-key":
        reference = sql.Identifier(schema, "acceptance_mart_reference")
        conn.execute(sql.SQL("ALTER TABLE {} ADD UNIQUE (current_month)").format(table))
        conn.execute(sql.SQL(
            "CREATE TABLE {} (reference_month text REFERENCES {} (current_month))"
        ).format(reference, table))
        inserted = conn.execute(sql.SQL("INSERT INTO {} SELECT current_month FROM {}").format(reference, table))
        assert inserted.rowcount > 0
        assert conn.execute("SELECT 1 FROM pg_constraint WHERE confrelid = %s::regclass AND contype = 'f'",
                            (table.as_string(conn),)).fetchone()
        return "foreign.key"
    if hazard == "numeric-typmod":
        conn.execute(sql.SQL("ALTER TABLE {} ALTER COLUMN cashflow_net TYPE numeric(12,2)").format(table))
        assert conn.execute(sql.SQL("SELECT count(*) FROM {} WHERE cashflow_net IS NOT NULL").format(table)).fetchone()[0]
        assert conn.execute(
            "SELECT numeric_precision, numeric_scale FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s AND column_name = 'cashflow_net'",
            (schema, PG_HAZARD_TARGET),
        ).fetchone() == (12, 2)
        return "column|schema|precision|numeric|type"
    assert hazard == "ownership"
    owner = sql.Identifier(role)
    conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(owner))
    conn.execute(sql.SQL("ALTER SCHEMA {} OWNER TO {}").format(sql.Identifier(schema), owner))
    relations = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = %s AND table_type = 'BASE TABLE'",
        (schema,),
    ).fetchall()
    for (name,) in relations:
        if name != PG_HAZARD_TARGET:
            conn.execute(sql.SQL("ALTER TABLE {} OWNER TO {}").format(sql.Identifier(schema, name), owner))
    conn.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON {} TO {}").format(table, owner))
    return r"\b(?:owns?|owner|ownership)\b"


def run_pg_hazards(base_env, command, digest, pg_dump, snapshots, legacy_publications):
    directory = Path(os.environ["CURRENCY_LEGACY_PG_HAZARDS"])
    dsn = base_env["HOMELAB_ANALYTICS_REPORTING_POSTGRES_DSN"]
    for hazard in PG_HAZARDS:
        warehouse = directory / f"{hazard}.duckdb"
        manifest = json.loads((directory / f"{hazard}.json").read_text())
        schema = manifest["postgres_schema"]
        assert manifest["drift_relation"] == PG_HAZARD_TARGET
        assert digest(warehouse) == manifest["warehouse_sha256"]
        facts_and_history(warehouse, dsn, manifest, snapshots)
        legacy_publications(dsn, manifest)
        role = "currency_hazard_" + uuid4().hex if hazard == "ownership" else None
        with psycopg.connect(dsn) as conn:
            reason = create_pg_hazard(conn, schema, hazard, role)
        try:
            candidate_dsn = dsn if role is None else make_conninfo(
                dsn, options=f"-c role={role}"
            )
            if role is not None:
                with psycopg.connect(candidate_dsn) as conn:
                    assert conn.execute("SELECT current_user, rolsuper FROM pg_roles WHERE rolname = current_user").fetchone() == (role, False)
                    table = sql.Identifier(schema, PG_HAZARD_TARGET).as_string(conn)
                    assert conn.execute(
                        "SELECT pg_has_role(current_user, relowner, 'MEMBER'), "
                        "has_table_privilege(current_user, oid, 'TRUNCATE') "
                        "FROM pg_class WHERE oid = %s::regclass", (table,),
                    ).fetchone() == (False, True)
            env = dict(base_env, HOMELAB_ANALYTICS_ANALYTICS_DATABASE_PATH=str(warehouse),
                       HOMELAB_ANALYTICS_REPORTING_POSTGRES_DSN=candidate_dsn,
                       HOMELAB_ANALYTICS_REPORTING_SCHEMA=schema)
            before = (digest(warehouse), pg_dump(dsn, schema))
            for args in (["--check"], []):
                result = command(args, env, require_success=False)
                after = (digest(warehouse), pg_dump(dsn, schema))
                assert_target_refusal(result, PG_HAZARD_TARGET, before, after, reason)
            facts_and_history(warehouse, dsn, manifest, snapshots)
        finally:
            if role is not None:
                with psycopg.connect(dsn) as conn:
                    conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
                    conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
