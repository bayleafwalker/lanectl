# Lane history and shared admission

Use the existing Vuoro Work surface for the workstation gateway proof. Verify
the required claim-to-outcome scenarios on demand against owner records as
they occur in ordinary operation. LANECTL policy history remains on one writer
for that proof.
Neither Work coordination nor remote visibility into Work requires a served
LANECTL event stream. The retry journal remains host-local SQLite.

## Replay ownership

The [event contract](../../src/lanectl/contracts.py) is the schema of record.
These rows classify its event families by what a successor must recover.

| Events | Producer and replay consumer | Owner-side reconstruction |
| --- | --- | --- |
| `release.published`, `release.publication.invalidated`, `policy.revised` | Publication, release sync and policy tooling record changes. Publication checks and delivery policy resolve the exact release revision, provenance, invalidation and effective policy. | Git recovers immutable content by digest or commit. A Work reference does not prove local publication, invalidation or which policy an admission used. Preserve the lane observations. |
| `item.claimed`, `attempt.finished`, `gate.result`, `decision.recorded`, `experiment.recorded`, `item.parked`, `item.requeued`, `progress.reviewed`, `evaluation.recorded`, `integrator.fix` | Runner, evaluator and recovery paths drive item state, retry limits, gated candidacy, reaping and feedback. | Work provides run identity, lease, appended evidence and terminal disposition for coordinated attempts. Preserve local events where evidence omits worker identity, same-release attempt order, gate details, progress rulings, policy transitions or retry state. A lane decision is distinct from a terminal Work Decision. |
| `train.built`, `train.deployed`, `train.torn_down`, `landing.planned`, `item.landed`, `work.synced` | Train, deploy, integrator and reconciliation paths guard tested-head landing, expiry, cleanup and uncertain Work completion. | Git, deploy targets and Work own their respective effects and outcomes. Reconstruct current effect facts at those owners. Lane history preserves the exact checked head, attempt membership, cleanup progress and join from the lane receipt to Work. |
| `usage.recorded`, `window.observed`, `capacity.observed`, `capacity.reserved`, `capacity.reconciled`, `lane.decision`, `burn.planned`, `admission.shadow` | Usage hooks, probes, runner, burn and steering project provider observations and pool reservations. Decision/proposal records associate events with policy and attempts. | Work can attribute attempts and carry evidence. Its repository-scoped Work lease cannot serialize reservations across different items in one provider pool. Active claims, unresolved reservations and the capacity basis used at admission need a common read and commit boundary wherever writers share a policy. |
| `triage.proposed` | Triage records emitted fingerprints for deduplication. | Work may hold a resulting item and reference. Its presence cannot reconstruct proposals that were only emitted locally. Preserve the fingerprint when resuming the same policy writer. |

The Work client records selected candidate and landing observations and reports
outcomes. Do not treat those observations as a full historical lane event
export. Build shared visibility from Work, Git and target receipts, retaining
unknown state where an owner lacks evidence.

## Scope and rollout

[`runner.admit`](../../src/lanectl/runner.py) calculates running and accepted
unlanded counts across the entire log, computes the same-day lane limit and
uses a common provider pool projection. Its locked section records a claim
and capacity reservation before returning. The optional
[`StreamStore`](../../src/lanectl/stream_store.py) makes the event batch atomic
and fences on a revision for a single `(workspace, repository, stream)`.
The [scope test](../../tests/stage9/test_stream_store.py) proves that stale
approval loses inside one stream but both writes succeed in disjoint repository
streams. Neither a backend substitution nor a per-item Work lease changes
that result.

Retain one writer per shared policy for the initial Work proof. Prepare the
off-workstation pilot with a distinct public-only authority and explicitly
independent caps and provider pool, or transfer exclusive ownership of the
pilot policy before that pilot begins. If those conditions cannot be
proved, hold that pilot. A requirement for independent writers to use the same
caps or provider pool is enough to require a shared authoritative admission
boundary. A visibility-only requirement is satisfied through projections.

Before accepting concurrent writers, bind the scope to the actual policy
owner, model the cross-repository transaction and prove isolation. Keep
repository-scoped event access. An internal policy lock or commit record may
span member repositories, but readable event payloads must stay partitioned.
Current stream import accepts a mixed source and selects one repository's
stream. Do not use this procedure for mixed authority history without a
scope-preserving migration and data-class review.

Evaluate PostgreSQL/CloudNativePG first when a shared policy owner is required.
Measure transactional revision checks, stable snapshots and exact
principal-bound batch replay against the current SQLite owner. Require an
explicit schema/version gate, owner-assigned scopes, bounded roles, failover
behavior, and recovery from approved off-node custody. Use a disposable
fresh-owner restore and compare canonical event and batch data before
approving import or selecting served authority. Keep existing SQLite stream
qualification as a reference for comparison and offline recovery.

The PostgreSQL migration runs in the owner environment with Psycopg available.
Supply the migration connection through `VUORO_LANE_POSTGRES_MIGRATION_DSN`
and run `lanectl stream init-postgres --runtime-role ROLE`. Provision the
named runtime role before migration. Start Vuoro with its separate runtime
connection only after the migration succeeds. The migration grants the runtime
role schema usage, scoped-table reads and inserts, and head revision updates.
