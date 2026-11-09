# Decision records and capacity feedback

**Status:** accepted operator planning direction, 2026-11-09. Fields, interfaces
and budgets below are proposals; implementation and provider entitlement remain
unqualified. Companion to the
[Vuoro direction](https://github.com/bayleafwalker/vuoro/blob/main/docs/plans/2026-11-09-decision-records-and-lane-feedback.md).

## Extend the existing owner

Lanectl owns allocation and admission through [capacity](../../src/lanectl/capacity.py),
[windows](../../src/lanectl/windows.py), [probe](../../src/lanectl/probe.py),
[burn](../../src/lanectl/burn.py) and [learning](../../src/lanectl/learning.py).
Extend these projections and the runner. The current
[allocation values](../../governance/allocation.toml) are placeholders, including
the token budget and five-hour window; they establish no provider entitlement.
CLI usage statistics and parsed denials also need source qualification.

## Record decisions and their consequences

Each dispatch, rerun, escalation, allocation and preliminary-acceptance decision
emits a compact record: work/attempt identity, decision kind, basis references
and snapshot time, eligible alternatives, selection mechanism, chosen action,
policy revision, validity conditions and expiry. Record proposed and applied
actions separately; preserve refused, expired and superseded recommendations.
Join outcomes through stable IDs, keeping when facts applied and when they were
learned. Count expected decisions from releases, claims and runtime transitions
independently of received records. Include durable allocation-cycle/request/
proposal triggers for no-dispatch cycles, refusals and unapplied advice. Without
an independent denominator, that decision class's coverage remains unknown.

Store actual selection probabilities when known, separately from model
confidence. The runner's deterministic weighted hash is not random assignment:
retain its mechanism and eligible weights, with deterministic 1/0 probabilities
conditional on its inputs. Do not invent exploratory propensities.

Add a versioned contract through `contracts.py`; do not overload today's
`decision.recorded` gate/candidate vocabulary or Vuoro's authoritative Decision.
Candidate acceptance remains preliminary; deterministic gates and the existing
integration authority decide what lands. Cheap agents and advisory Jev consume
bounded projections within existing data restrictions. Jev grants no authority.

## Account for the actual subscription pool

Qualify observations by provider, account/subscription pool, source and scope,
unit, observation time, freshness deadline, and measured/estimated/unknown basis.
Track every applicable limit window and its verified refresh rule; provider and
model names alone do not identify a shared pool. Fixed and rolling windows need
their own semantics. Unknown capacity never becomes zero usage or free capacity.

Separate cumulative snapshots, incremental usage, in-flight reservations and
outside-lane spend. Deduplicate overlapping sources; reserve atomically at
admission and reconcile reservations against actual usage on completion or
recovery. Attribute delayed usage to its consumption interval, preserving
uncertainty across resets. Account for interactive sessions and other hosts;
unseen spend is a coverage gap, not spare quota.

Retain the previously authorized static/reactive policy when sources are stale,
missing or unsupported; placeholder values never establish entitlement or burn
capacity. Allocation cannot authorize cross-provider failover. Revalidate
pool, window and model when applying a burn plan; correlate the plan with the
actual dispatch. Preserve running work and review-WIP limits. Policy revisions
set a minimum allocation dwell and change threshold to prevent oscillation;
denials override them immediately.

## Use the feedback

Run two loops: choose the next useful observation with deterministic rules, and
allocate expiring capacity across eligible lanes using qualified balances.
Compare quota consumed with work landed, repairs and integrator effort; burning
unused capacity is not itself success. Retain model, harness, environment and
policy revisions together. Extend `learning.py` suggestions where case volume
outpaces configuration churn; elsewhere report directional cost and burden.
Fault-injected correctness is a separate invariant, never a statistical reward.

## Keep the accounting cheaper than the work

Proposed low-effect budget: envelope ≤2 KiB using shared references, p95 local
append ≤10 ms, no routine model call. Optional inference allowance is at most
1% of already-observed non-adviser usage in the same account pool/window and
units. Reserve each call's bounded maximum charge/consumption before dispatch,
including outstanding adviser reservations. Unknown/zero denominators or no
reliable bound disable optional calls; deterministic decisions continue.
Reconcile actual usage and stop further optional calls on overrun. This is an
accounting allowance, not a provider-enforced quota. Include referenced snapshot
storage and processing in overhead. Increase evidence depth with effect class;
reduce optional detail on pressure while preserving identity and owner-required
lifecycle/receipts.

Implement against real lane work without a new benchmark prerequisite. Verify
shared pools, stale observations, duplicate/delayed usage, reservation races and
plan/application mismatch. If accounting is unreliable, restore the previously
authorized static/reactive policy and retain records for diagnosis.
