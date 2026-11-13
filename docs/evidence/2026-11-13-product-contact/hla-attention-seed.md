# Synthetic attention fixture qualification

Canonical HLA source9cf62cb was exercised without repository edits. The public
demo generator and seeder passed eight ingestion runs, but on2026-11-13 its queue
contained only three utilities reviews and one finance upcoming cost. It had no
anomalies, renewals or slash-bearing IDs. Those observations were worker-measured;
the original demo artifacts remain session-local under /tmp.

The reusable `contrib/qualification/hla_attention_seed.py` uses explicit synthetic
inputs through production normalized loaders, transformations and reporting. It
imports no test module. Local stores are confined to a dedicated empty /tmp root.
The source revision argument is required and labeled caller-supplied; the caller
must independently bind the interpreter, import path and actual checkout or image.

The coordinator independently ran its local mode and replayed its final Postgres
mode in a fresh loopback-only disposable Postgres16 container. Both observed one
anomaly, three renewals, two reviews and two upcoming costs across finance and
utilities. All returned IDs were unique. Two payment records had distinct IDs;
the normalized contract-price loader accepted `synthetic/utility`, preserved in
review and renewal IDs. The CSV adapter instead hashes contract IDs.

Missing/invalid revisions and a nonempty local root failed with exit2; the local
sentinel survived. Those local guard observations bind the earlier script digest,
before the Postgres-only freshness correction. Final Postgres mode atomically
creates its schema without `IF NOT EXISTS`; reuse failed with exit2 and preserved
the full attention publication and a sentinel. A wrong schema prefix failed
without creating that schema. The coordinator's disposable container was removed
and a subsequent inspect confirmed absence. Raw observations are adjacent JSON.

Read-only Sage review passed the local scaffold and then cleared the schema reuse
finding after the atomic-create correction. Subsequent failures can still leave a
new disposable schema behind; its owning caller must clean it up.

This proves fixture availability and synthetic publication/read parity. It does
not prove source detail APIs, HTTP encoding, permission enforcement, ranking,
individual destinations or UI behavior. It does not assert distinct records of
every kind or exercise promotion/snapshot capture.

The canonical9cf application binding is now measured separately in
`hla-compose-binding/qualification.json`. A clean archived source built its own
API image and used isolated Compose PostgreSQL/MinIO dependencies, checked-in
example authentication and a fresh synthetic reporting schema. The helper ran
through image Python before API startup. The real API returned eight unique
attention IDs across all four kinds and both domains; their complete set matched
the helper's PostgreSQL publication captured before API startup. Counts and the
helper-emitted payment/slash IDs also matched.

The actual HTTP checker was forced to fail with the API pointed at a different
schema: health, readiness and login passed, but the existing list endpoint
returned404 for its missing published relation and the checker exited1. Recreating
only the API with the seeded schema restored the full check, exit0. An initial
scratch classifier incorrectly expected500/503; that harness failure and cleanup
are recorded separately rather than called an application defect. The coordinator
independently verified all three owned projects' containers, volumes, networks
and image tags were absent after cleanup.

This binds the explicit synthetic schema, not the default reporting schema. It
does not exercise OIDC/source permissions, new record endpoints, web navigation
or the final candidate's real train/dev delivery. HLA1593 remains active.

The committed helper and observations are cross-host-replicated. Their original
/tmp warehouses, runner scripts and logs are session-local.
