"""Run with LANECTL_TEST_POSTGRES_BIN pointing to a local PostgreSQL bin directory."""

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from lanectl.cli import main
from lanectl.contracts import make_event
from lanectl.stream_postgres import PostgresStreamStore, initialize_postgres
from lanectl.stream_store import StreamError


def test_postgres_owner_contract(tmp_path, monkeypatch, capsys):
    postgres_bin = os.environ.get("LANECTL_TEST_POSTGRES_BIN")
    if not postgres_bin:
        pytest.skip("local PostgreSQL bin directory was not selected")
    import psycopg

    bin_path = Path(postgres_bin)
    data = tmp_path / "db"
    subprocess.run(
        [
            bin_path / "initdb",
            "-D",
            data,
            "-U",
            "postgres",
            "-A",
            "trust",
            "--no-locale",
            "--encoding=UTF8",
        ],
        check=True,
        capture_output=True,
    )
    ctl = [bin_path / "pg_ctl", "-D", data]
    subprocess.run(
        [
            *ctl,
            "-l",
            tmp_path / "postgres.log",
            "-o",
            f"-h '' -k '{tmp_path}'",
            "-w",
            "start",
        ],
        check=True,
        capture_output=True,
    )
    try:

        def connect():
            return psycopg.connect(host=tmp_path, dbname="postgres", user="postgres")

        with pytest.raises(StreamError, match="schema is missing or incompatible"):
            PostgresStreamStore(connect)
        runtime_user = "lane-runtime"
        with connect() as db:
            db.execute('CREATE ROLE "lane-runtime" LOGIN')
        with pytest.raises(StreamError, match="explicit PostgreSQL runtime role"):
            initialize_postgres(connect, runtime_role="PUBLIC")
        monkeypatch.delenv("VUORO_LANE_POSTGRES_MIGRATION_DSN", raising=False)
        assert main(["stream", "init-postgres", "--runtime-role", runtime_user]) == 1
        assert "MIGRATION_DSN is required" in capsys.readouterr().err
        with connect() as db:
            db.execute("CREATE ROLE lane_migration LOGIN")
            db.execute("CREATE SCHEMA lane")
        dsn = psycopg.conninfo.make_conninfo(
            host=tmp_path, dbname="postgres", user="lane_migration"
        )
        monkeypatch.setenv("VUORO_LANE_POSTGRES_MIGRATION_DSN", dsn)
        assert main(["stream", "init-postgres", "--runtime-role", runtime_user]) == 1
        assert "different migration role" in capsys.readouterr().err
        with connect() as db:
            db.execute("ALTER SCHEMA lane OWNER TO lane_migration")
        monkeypatch.setenv("VUORO_LANE_POSTGRES_MIGRATION_DSN", dsn)
        assert main(["stream", "init-postgres", "--runtime-role", runtime_user]) == 0
        assert "schema 1 initialized" in capsys.readouterr().out
        assert main(["stream", "init-postgres", "--runtime-role", runtime_user]) == 1
        assert capsys.readouterr().err == "Lane PostgreSQL initialization failed\n"

        def connect_runtime():
            return psycopg.connect(host=tmp_path, dbname="postgres", user=runtime_user)

        store = PostgresStreamStore(connect_runtime)
        event = make_event(
            "item.parked", {"reason": "qualification"}, item_id="fixture"
        )
        scope = ("workspace", "repo-a", "control")

        def append(key, revision):
            try:
                return store.append(*scope, "principal", key, revision, [event])
            except StreamError as error:
                return error.code

        assert append("batch-one", 0)["revision"] == 1
        with ThreadPoolExecutor(max_workers=2) as workers:
            outcomes = list(
                workers.map(lambda key: append(key, 1), ("batch-two", "batch-three"))
            )
        assert "revision-conflict" in outcomes
        assert sum(isinstance(outcome, dict) for outcome in outcomes) == 1
        assert append("batch-one", 0)["replayed"]
        assert store.read(*scope, through=1) == {
            "revision": 1,
            "head_revision": 2,
            "events": [event],
            "next_after": 1,
            "has_more": False,
        }
        assert store.read("workspace", "repo-b", "control")["revision"] == 0
        with pytest.raises(StreamError, match="different content"):
            store.append(*scope, "principal", "batch-one", 0, [event, event])
        assert store.read(*scope)["head_revision"] == 2
        for forbidden in (
            "DELETE FROM lane.events",
            "UPDATE lane.batches SET digest = 'edited'",
            "DROP TABLE lane.events",
            "CREATE TABLE lane.unexpected (id integer)",
        ):
            with (
                pytest.raises(psycopg.errors.InsufficientPrivilege),
                connect_runtime() as db,
            ):
                db.execute(forbidden)
        assert store.read(*scope)["head_revision"] == 2
        with psycopg.connect(dsn) as migration:
            migration.execute('GRANT DELETE ON lane.events TO "lane-runtime"')
        with pytest.raises(StreamError, match="permissions exceed") as error:
            PostgresStreamStore(connect_runtime)
        assert error.value.code == "unsafe-runtime-role"
        with psycopg.connect(dsn) as migration:
            migration.execute('REVOKE DELETE ON lane.events FROM "lane-runtime"')
        assert PostgresStreamStore(connect_runtime).read(*scope)["head_revision"] == 2
    finally:
        subprocess.run(
            [*ctl, "-m", "immediate", "-w", "stop"], check=True, capture_output=True
        )
