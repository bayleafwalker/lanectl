"""PostgreSQL repository streams for the Lane owner."""

import json
import os
import sys
from contextlib import contextmanager

from .stream_store import (
    MAX_BATCH,
    SCHEMA_VERSION,
    StreamError,
    StreamStore,
    encode,
    validate_batch,
)


def initialize_postgres(connect, *, runtime_role=None):
    """Initialize a new owner schema using a migration-role connection factory."""
    if runtime_role is not None and (
        not isinstance(runtime_role, str)
        or not runtime_role
        or runtime_role.lower() == "public"
    ):
        raise StreamError(
            "invalid-role", "an explicit PostgreSQL runtime role is required"
        )
    with connect() as db:
        if db.autocommit:
            raise StreamError(
                "store-unavailable",
                "lane migration requires a transactional connection",
            )
        owner = db.execute("""
            SELECT nspowner = CURRENT_USER::regrole
            FROM pg_catalog.pg_namespace WHERE nspname = 'lane'
        """).fetchone()
        if owner is None:
            db.execute("CREATE SCHEMA lane")
        elif owner != (True,):
            raise StreamError(
                "incompatible-schema",
                "Lane schema belongs to a different migration role",
            )
        db.execute("""
            CREATE TABLE lane.schema_version (
                singleton boolean PRIMARY KEY CHECK (singleton), version integer NOT NULL
            );
            CREATE TABLE lane.heads (
                workspace text NOT NULL, repo text NOT NULL, stream text NOT NULL,
                revision bigint NOT NULL DEFAULT 0,
                PRIMARY KEY (workspace, repo, stream)
            );
            CREATE TABLE lane.events (
                workspace text NOT NULL, repo text NOT NULL, stream text NOT NULL,
                revision bigint NOT NULL, event text NOT NULL, principal text NOT NULL,
                PRIMARY KEY (workspace, repo, stream, revision),
                FOREIGN KEY (workspace, repo, stream) REFERENCES lane.heads
            );
            CREATE TABLE lane.batches (
                workspace text NOT NULL, repo text NOT NULL, stream text NOT NULL,
                principal text NOT NULL, key text NOT NULL, digest text NOT NULL,
                result text NOT NULL, PRIMARY KEY (workspace, repo, stream, principal, key),
                FOREIGN KEY (workspace, repo, stream) REFERENCES lane.heads
            );
        """)
        db.execute(
            "INSERT INTO lane.schema_version VALUES (true, %s)", (SCHEMA_VERSION,)
        )
        if runtime_role is not None:
            role = db.execute("SELECT quote_ident(%s)", (runtime_role,)).fetchone()[0]
            db.execute(f"GRANT USAGE ON SCHEMA lane TO {role}")
            db.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA lane TO {role}")
            db.execute(
                f"GRANT INSERT ON lane.heads, lane.events, lane.batches TO {role}"
            )
            db.execute(f"GRANT UPDATE (revision) ON lane.heads TO {role}")


def migrate_from_environment(runtime_role):
    """Run the operator command without exposing a database credential."""
    dsn = os.environ.get("VUORO_LANE_POSTGRES_MIGRATION_DSN")
    if not dsn:
        print("VUORO_LANE_POSTGRES_MIGRATION_DSN is required", file=sys.stderr)
        return 1
    try:
        from psycopg import Error, connect
    except ImportError:
        print(
            "Lane PostgreSQL migration requires psycopg in the owner environment",
            file=sys.stderr,
        )
        return 1
    try:
        initialize_postgres(lambda: connect(dsn), runtime_role=runtime_role)
    except StreamError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Error:
        print("Lane PostgreSQL initialization failed", file=sys.stderr)
        return 1
    print(f"Lane PostgreSQL schema {SCHEMA_VERSION} initialized")
    return 0


class PostgresStreamStore(StreamStore):
    """Owner-side stream store using non-autocommit PostgreSQL connections."""

    def __init__(self, connect):
        self.connect = connect
        with self._db() as db:
            version = db.execute(
                "SELECT version FROM lane.schema_version WHERE singleton"
            ).fetchone()
            if version != (SCHEMA_VERSION,):
                raise StreamError(
                    "incompatible-schema", "lane stream migration required"
                )
            db.execute(
                "SELECT workspace, repo, stream, revision FROM lane.heads LIMIT 0"
            )
            db.execute(
                "SELECT workspace, repo, stream, revision, event, principal FROM lane.events LIMIT 0"
            )
            db.execute(
                "SELECT workspace, repo, stream, principal, key, digest, result FROM lane.batches LIMIT 0"
            )

    @contextmanager
    def _db(self):
        try:
            with self.connect() as db:
                if db.autocommit:
                    raise StreamError(
                        "store-unavailable",
                        "lane streams require transactional connections",
                    )
                yield db
        except StreamError:
            raise
        except Exception as exc:
            state = getattr(exc, "sqlstate", None)
            if state in {"42P01", "42703", "3F000"}:
                raise StreamError(
                    "incompatible-schema",
                    "lane stream schema is missing or incompatible",
                ) from exc
            raise StreamError(
                "store-unavailable", "lane stream transaction unavailable"
            ) from exc

    def read(self, workspace, repo, stream, after=0, limit=MAX_BATCH, through=None):
        scope = self._scope(workspace, repo, stream)
        if (
            type(after) is not int
            or after < 0
            or type(limit) is not int
            or not 1 <= limit <= MAX_BATCH
        ):
            raise StreamError("invalid-cursor", "invalid cursor or limit")
        with self._db() as db:
            row = db.execute(
                "SELECT revision FROM lane.heads WHERE (workspace, repo, stream) = (%s, %s, %s)",
                scope,
            ).fetchone()
            head = row[0] if row is not None else 0
            through = head if through is None else through
            if type(through) is not int or not after <= through <= head:
                raise StreamError("invalid-cursor", "snapshot revision unavailable")
            rows = db.execute(
                "SELECT revision, event FROM lane.events WHERE (workspace, repo, stream) = (%s, %s, %s) "
                "AND revision > %s AND revision <= %s ORDER BY revision LIMIT %s",
                (*scope, after, through, limit),
            ).fetchall()
        return {
            "revision": through,
            "head_revision": head,
            "events": [json.loads(row[1]) for row in rows],
            "next_after": rows[-1][0] if rows else after,
            "has_more": bool(rows and rows[-1][0] < through),
        }

    def append(
        self, workspace, repo, stream, principal, key, expected_revision, events
    ):
        scope = self._scope(workspace, repo, stream)
        frozen, digest = validate_batch(principal, key, expected_revision, events)
        with self._db() as db:
            db.execute(
                "INSERT INTO lane.heads (workspace, repo, stream) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                scope,
            )
            head = db.execute(
                "SELECT revision FROM lane.heads WHERE (workspace, repo, stream) = (%s, %s, %s) FOR UPDATE",
                scope,
            ).fetchone()[0]
            prior = db.execute(
                "SELECT digest, result FROM lane.batches "
                "WHERE (workspace, repo, stream, principal, key) = (%s, %s, %s, %s, %s)",
                (*scope, principal, key),
            ).fetchone()
            if prior is not None:
                if prior[0] != digest:
                    raise StreamError(
                        "idempotency-conflict", "same batch key has different content"
                    )
                return {**json.loads(prior[1]), "replayed": True}
            if head != expected_revision:
                raise StreamError(
                    "revision-conflict", "stream changed; reread before a new decision"
                )
            revision = head + len(frozen)
            db.cursor().executemany(
                "INSERT INTO lane.events VALUES (%s, %s, %s, %s, %s, %s)",
                [
                    (*scope, head + offset, encode(event), principal)
                    for offset, event in enumerate(frozen, 1)
                ],
            )
            result = {
                "previous_revision": head,
                "revision": revision,
                "count": len(frozen),
                "replayed": False,
            }
            db.execute(
                "INSERT INTO lane.batches VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (*scope, principal, key, digest, encode(result)),
            )
            db.execute(
                "UPDATE lane.heads SET revision = %s WHERE (workspace, repo, stream) = (%s, %s, %s)",
                (revision, *scope),
            )
            return result
