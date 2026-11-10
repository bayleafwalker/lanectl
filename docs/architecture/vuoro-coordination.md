# Vuoro coordination for native lanes

`lanectl.coordination` implements the existing Vuoro `invocation/v1` protocol using
only the Python standard library. Native harnesses still execute work. Sprintctl
owns run bindings, leases and outcome settlement; lanectl does not synthesize a
terminal Decision from a candidate or from an outcome report.

Configuration is opt-in and planner-owned. Add `governance/vuoro.toml` with a
section for each participating repository:

```toml
[repos.example]
endpoint = "https://api.example.invalid"
repo_id = "the-repository-id-admitted-by-the-owner"
expected_environment = "the-environment-name-from-handshake"
token_env = "LANECTL_RUNNER_TOKEN"
```

The token is resolved from the named environment variable at request time. The
journal never stores it. Enroll an appropriately scoped runner using the owner's
existing flow, and keep that credential outside worker environments. HTTPS is
required outside loopback; redirects are refused. `lanectl coordinate example`
checks the authenticated handshake and catalog without claiming work.

## Native integration API

Call `configured(repo_name)` to obtain a coordinator (or `None` for an unconfigured
repo). Before native execution, call `start(attempt_id, item_id, model_id,
profile_digest, recipe_id="lanectl/v1")`, then enter
`guard(attempt_id, on_lost=cancel_native_worker)`. The guard verifies ownership
before entry, heartbeats at the owner's advertised interval, cancels execution on
an owner refusal or uncertain heartbeat, and checks expiry before returning.
Native integration must supply a cancellation callback and call
`guard.assert_active()` before publishing candidate effects. A local callback is
not effect authority; target owners must still recheck their own grants.

`append_evidence(attempt_id, key, kind, body, ref=None)` links observations through
the existing run evidence chain. `report_outcome(attempt_id, outcome, summary,
checks=None, payload=None)` returns the owner's settlement result unchanged;
`awaiting-verification` is not success. Reports have stable logical keys. Use a
new explicit key only for a deliberately distinct outcome report, never to get
around a refused or uncertain operation.

## Recovery and durability

The default SQLite journal is under `LANECTL_STATE`, scoped to endpoint,
repository and expected environment. This journal is **host-persistent recovery
state**, not cross-host work authority. It stores immutable request identities,
exact pending envelopes and received owner responses. Lost acknowledgements
replay the same request and idempotency key; changed payloads under the same key
are refused. Starting an existing attempt revalidates its acquire operation with
the owner, rather than treating a cached lease as current. Changed principal,
expired lease and superseded claim refusals stop execution. Token rotation cannot
transfer a predecessor principal's run or lease.

Evidence tail lookup and append are serialized for processes sharing a journal.
A competing writer outside that journal may cause an owner chain conflict; that
refusal stays visible. The journal does not invent a new sequence or silently
rebase an uncertain append.

## Served lane event authority

`lanectl.stream_store` owns schema 1, validated event storage, snapshot reads and
atomic idempotent expected-revision batch append. Its optional
`lanectl.vuoro_adapter.register_lane_catalog` composes into Vuoro's immutable
catalog as `lane.stream.read-v1` (`work:read`) and `lane.stream.append-v1`
(`work:evidence`). Both operations derive workspace, repository and principal
from verified invocation context and recheck scope before serving a replay.
They grant no Sprintctl claim, terminal Decision or target effect authority.

`RemoteEventLog` implements the existing append/read/locked interface. One
`locked` block becomes one atomic served batch. Competing-host revision conflicts
fail before admission returns a claim. An uncertain response retains exact
pending bytes on the host and replays them under the same idempotency key.
Reads page through a fixed snapshot revision; they never combine partial views
from different stream revisions. These guarantees require the lane owner
operations, not the per-run evidence chain.

The host-persistent `LANECTL_STATE/backend.json` marker selects one authority for
CLI invocations, hooks and the timer, including calls outside the checkout.
`open_log()` never falls back to local JSONL if a selected served owner fails.
`EventLog(path)` remains the explicit local/snapshot implementation for tests.

### Release, storage and cutover

The source implementation does not activate or qualify a deployment. A service
release must pin the built lanectl wheel, source revision and artifact digest in
its immutable composition manifest, alongside the existing work/audit/knowledge
owners. The new optional lane descriptor selects module `lanectl.vuoro_adapter`,
registration `register_lane_catalog`, API `v1`, schema `1`. Deployment supplies
`VUORO_LANE_DATABASE`; runtime startup checks compatibility and never migrates.
The gateway must admit exactly the two repository-scoped stream operations for
the enrolled runner.

The SQLite owner requires one service replica and a persistent local/block
filesystem volume with working SQLite locks; do not place it on a network
filesystem or an ephemeral container layer. Back up using SQLite's online backup
API (copying a live WAL database file alone is incomplete), store the backup in
the estate's qualified backup system, and rehearse a quiesced restore into a new
owner instance. Stop service writes before restore. Persistent volume, backup
and restore evidence is required before calling hosted storage
**durable-authoritative**. A disposable development database is only
**host-persistent**. The hosted API allows cross-host clients, but does not by
itself establish replicated storage or recovery.

With all writers paused, initialize the owner's configured database explicitly,
then inspect/import history from the current authority:

```sh
lanectl stream init /state/lanectl/owner.sqlite
lanectl stream import --repo lanectl --home /projects/dev/lanectl \
  --source /home/bayleaf/.local/state/lanectl/events.jsonl
# Read the dry-run source_sha256, then use that exact value:
lanectl stream import --repo lanectl --home /projects/dev/lanectl \
  --source /home/bayleaf/.local/state/lanectl/events.jsonl \
  --source-sha256 <dry-run-digest> --execute
lanectl stream configure --repo lanectl --home /projects/dev/lanectl
```

The migration command runs on the owner host; import/configure run on the lane
host using its configured owner and runner credential. Import preserves event
payloads, timestamps and ordering in bounded idempotent batches, refuses a
mismatched served prefix, checks source drift, and records source and canonical
event hashes in `stream-import-receipt.json`. It does not switch authority.
Configure refuses an empty or mismatched destination when local history exists.
Resume writers only after final history verification and marker selection.
Keep JSONL as a historical source after switching; never run independent local
and served writers as parallel authorities. Recovery/import receipts remain
**host-persistent**, even when the selected stream has qualified hosted durability.

## Verification

HTTP-owner tests cover the invocation envelope, chain linkage, exact replay after
lost registration/evidence/outcome acknowledgements, changed payload refusal,
restart lease checks, credential rotation, environment mismatch, correlation
mismatch, expiry and revocation while native execution is running.

Validate against actual owner code using Vuoro's development environment:

```sh
/path/to/vuoro/.venv/bin/python contrib/verify-vuoro-contracts.py \
  --sprintctl-root /path/to/sprintctl --vuoro-root /path/to/vuoro
```

The verifier validates generated operation arguments with Sprintctl's actual
catalog schemas and envelopes with Vuoro Service's actual model. It also forces
both validators to reject incompatible requests. Synthetic tests and schema
compatibility establish no deployed availability, enrollment or live product
qualification.
