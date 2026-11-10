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

## Authoritative event storage remains separate

This module does not replace the lane JSONL event log. Existing run evidence
`tail` and `entry` operations can replay one caller-owned run chain. They do not
provide the atomic multi-event transaction used by `EventLog.locked()` for
admission (claim, capacity reservation and dispatch record), nor a shared stream
across different named-host runner principals. A local SQLite journal cannot
supply either missing owner guarantee.

A served lane event store needs a lanectl-owned repository stream with paginated
revisioned reads, idempotent atomic batch append against an expected revision,
contract validation, and explicitly authorized cross-run writers. Its adapter,
Vuoro composition and runner operation allowlist must be implemented and tested
before changing event-log authority. Until that path is qualified, JSONL remains
the lane authority and is host-persistent; served run/lease/evidence/outcome facts
remain authoritative at their existing owner.

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
