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

The token is resolved from the named environment variable at request time. For
systemd services, replace `token_env` with `credential_name = "lanectl-runner"`
and load that credential through `LoadCredential=`. Exactly one credential
source is required. The file is read again for each request, so rotation does
not require putting the token in the coordinator or candidate-check environment.
The journal never stores it. Enroll an appropriately scoped runner using the owner's
existing flow, and keep that credential outside worker environments. HTTPS is
required outside loopback; redirects are refused. `lanectl coordinate example`
checks protocol, environment and catalog compatibility without claiming work.
Discovery can be public: a successful catalog response does not prove that the
runner credential authenticated. Qualification must also observe an authorized,
repository-scoped owner read. An `identity-required` refusal remains a blocker.

### Workstation service activation

Keep coordination disabled until runner enrollment is approved and a scoped
credential is installed outside the checkout. Coordinated train setup and checks
require `train_isolation = "namespace"` (the repository default) or the qualified
`"systemd"` backend. Namespace mode uses a minimal environment and makes known
credential paths inaccessible. This protects direct
file and environment access; it is not full
isolation against arbitrary hostile code sharing the operator's user identity.
The credential drop-in alone does not provide that isolation. Read the actual environment name
from the observed handshake; do not infer it from the URL. Validate the
configured repository with `lanectl coordinate` before changing its recurring
service. The optional `contrib/systemd/lanectl-tick-coordinated.conf` adds only
credential loading and the workstation CA bundle to the existing service. For a
one-off check, keep the draft configuration in a separate reviewed worktree:

```sh
systemd-run --user --pipe --wait --collect \
  --setenv=LANECTL_HOME=/path/to/reviewed-worktree \
  --setenv=SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
  -p LoadCredential=lanectl-runner:"$HOME/.config/vuoro/credentials/lanectl-runner.token" \
  "$HOME/.local/bin/lanectl" coordinate example
```

Install the optional drop-in only after validation:

```sh
install -Dm0644 contrib/systemd/lanectl-tick-coordinated.conf \
  ~/.config/systemd/user/lanectl-tick.service.d/coordinated.conf
systemctl --user daemon-reload
```

Use `credential_name` for timer activation. Exporting a token into the timer's
environment would also expose it to candidate train checks. The drop-in leaves
the credential value out of command arguments, unit text and process environments.
It does not enable the timer or select a served event authority. Keep JSONL
authoritative until the separate served-store qualification and cutover below.

Repository governance may explicitly select `train_isolation = "environment"`
for uncoordinated repositories. This strips inherited secrets but preserves host
ownership IDs; it provides no credential-file barrier. Sovite uses this exception
because its ownership checks reject UID 65534 projections under user namespaces:
its real baseline passed 2,797 tests while namespace execution failed 66 with
25 setup errors. The checks remain unchanged. Such trains can read same-user
credential files, including runner credentials for other repositories. With
coordination configured, `doctor` names every environment-only repository;
coordinated admission and execution refuse this mode. No command silently falls
back from a failed namespace. A different fenced backend needs separate full-suite
qualification before this exception can be removed.

The opt-in `systemd` backend in 0.2.5 uses the installed root-owned system service
and a separate static UID. Its actual Sovite run matches the ordinary baseline,
and direct-file/environment, timeout, cancellation and historical-recovery probes
pass. Repository policy promotion remains separate from source release. See the
[fenced-train guide](../fenced-train.md) for host prerequisites, measured limits
and qualification evidence.

A failed post-merge setup now fails the train rather than allowing a green check
to hide it. Rechecks and historical qualification use the same selected boundary.

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
