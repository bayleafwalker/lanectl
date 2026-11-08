---
doc_id: lanectl-adr-0001-autonomous-lanes
title: Autonomous implementation lanes, bootstrapped by dogfooding
purpose: decision
lifecycle: accepted
effective: 2026-11-08
subjects: [agent-delivery, model-routing, acceptance, capacity]
related: [agentops-model-routing, vuoro-accepted-outcome-learning]
supersedes: []
---

# ADR 0001: Autonomous implementation lanes

## Decision

Cheap workers produce, deterministic gates filter, expensive models integrate,
and interactive planner sessions shape the backlog. The system is built by its
own lanes: an interactive seed (stage 0) runs first, and every later component
is a lane-built replacement that runs in shadow mode against its scaffold.

## Three planes

| Plane | Owns | May |
| --- | --- | --- |
| Judgment | planner sessions, integrate lane, operator | change policy, land on main, approve promotion |
| Control | contracts, event log, projections, gates, admission | decide whether something may happen, never what is built |
| Execution | harness adapters, worktrees/sandboxes, CI, Flux | run work under a grant; replaceable behind its contract |

## Invariants

1. Only the integrate step (`lanectl land`, judgment plane) writes to main.
2. Implementers never write their own acceptance criteria. Acceptance lives in
   `backlog/<id>/` and is copied into the worktree as a protected seed commit.
3. Gates, scheduling and admission are deterministic.
4. State is an append-only event log; every view is a projection.
5. Governance paths change only through the judgment plane. Lanes may write
   them when a release scopes them explicitly; every gate still runs and the
   result is **parked for interactive review** (`lanectl approve`), never
   auto-accepted. Unscoped governance edits and any edit to acceptance files
   are hard protected-path parks.
6. Every attempt emits an ExperimentRecord, including failures.
7. Expiring capacity may be burned down; non-expiring spend never is.
8. The runner runs a released tag (`uv tool install` of `vX.Y.Z`), never the
   main it is building. Lanes build N+1 while N runs.
9. Integrator fixes are separate commits titled `fix(<attempt>): [<class>] ...`
   with class `spec-gap | model-error | gate-gap`, so the learning signal
   survives integration. Attribution (operator, 2026-11-08): only `model-error`
   counts against the model; `spec-gap` is the planner's, `gate-gap` the gates'.

## Contracts v1 (`src/lanectl/contracts.py`)

- **WorkRelease**: id, repo, base_sha, outcome, task_class, size, data_class,
  scope.paths, acceptance (exec commands + planner files), constraints,
  escalation conditions, allowances.
- **LaneRevision** (a RecipeRevision): routing weights, attempts, caps, gate
  parameters, protected paths. No threshold lives in code.
- **Events**: `release.published`, `item.claimed`, `attempt.finished`,
  `gate.result` (EvidenceSet), `decision.recorded` (Decision),
  `experiment.recorded` (ExperimentRecord), `train.built`, `item.landed`,
  `integrator.fix`, `item.parked`, `item.requeued`, and the capacity and policy
  families: `usage.recorded` (UsageEvent), `window.observed`
  (WindowObservation), `policy.revised` (AllocationPolicyRevision, lane
  revisions). Additive extension for stages 2-5 (2026-11-08): `admission.shadow`,
  `evaluation.recorded`, `landing.planned`, `triage.proposed`, `burn.planned`;
  payload shapes are pinned by `tests/strategies.py`.

Item states: ready → claimed → implemented → gated → candidate → in-train →
landed, or rejected → requeued (retry prefers a different model) or parked.

## Gates (cheapest first)

1. Diff policy: scope, protected paths, size budget, dependency manifests,
   existing tests unmodified, no skip/xfail/ignore markers.
2. New tests fail on base. Acceptance tests must also fail on base; if they
   pass there the release is a spec gap, not a worker failure.
3. Fixed acceptance commands run on the planner's bytes.
4. Per train: repo check on main plus accepted items (later, dev-namespace
   deploys with TTL and no production secrets).

## Data boundary

OpenCode Go routes leave the estate. On 2026-11-08 the operator cleared
public-repository material, including this repository's work-queue, contract,
gate and authority designs, for OpenCode Go DeepSeek, so lanes build lanectl
itself. Still excluded from external models: credentials and secret values,
private repositories (vuoro-cloud, appservice, cred-broker), served tracker
records, handoffs, telemetry, and customer or tenant data. A release with
`data_class = "restricted"`, or any release for a repo whose `data_class_floor`
is restricted, routes only to first-party models (adapter `claude`, not listed in
`external_models`): an allowlist, so an unknown or newly added model is never
routed restricted work. The Definition of Ready blocks a release with no
eligible model.

The planner writes releases, acceptance tests and policy values; lanes write
the code, governance code included, under review.

## Bootstrap ladder

| Stage | Interactive | Lanes | Scaffold replaced | Exit |
| --- | --- | --- | --- | --- |
| 0 Seed | contracts, gates, runner, OpenCode adapter, static caps, planner skill (minimal) | — | — | one item end to end; red-team test edit blocked (seed tests) |
| 1 Siblings | adapter contract | native OpenCode adapter with usage, Claude adapter, schemas, usage hook, metrics | — | every attempt logged with usage; ~20 items |
| 2 Capacity | projection semantics as property tests | probes, window detector, ledger, allocation projection, admission | static caps (shadow first) | shadow admission agrees for a week |
| 3 Acceptance | decision rules v1 | evaluator, gate jobs, dev-namespace train deploys | manual review per task class | agreement ≥ precision bar per class |
| 4 Integrator | authority config, fix budget | integrate skill, triage emitters | operator landing (shadow) | landing plans match |
| 5 Steering | routing limits, burn-down rules | learning projection, burn-down, views | hand-set weights | a window burned within WIP caps |
| 6 Fan-out | per-repo DoR + protected paths | per-repo wiring | — | homelab-analytics → sovite → vuoro-cloud (first-party routes only) |

### Implementation status (2026-11-08)

Every stage's lane work has landed (v0.1.14+); the exits are evidence clocks
that run from here.

| Stage | Landed | Evidence clock |
| --- | --- | --- |
| 2 | `probe`, `windows`, capacity projection, shadow admission (`admission.shadow`) | shadow admission agreement, one week |
| 3 | `evaluate` (rules in `governance/evaluator.toml`, rev 2 after first evidence) | per-class agreement ≥ precision bar; gate jobs and dev-namespace train deploys not yet built |
| 4 | integrator skill, `plan-landing` (shadow, `integrator.toml` authority empty), `triage`, reaper v2 | landing plans match operator landings |
| 5 | `learn` (suggest only), `burn` (plan/record/execute through admission), `view --html` | a window burned within WIP caps |
| 6 | repo overlay: protected paths, data-class floor, routing; first-party allowlist | per-repo wiring in `governance/repos.toml` |

Report sections are self-registering (`report_section()` in each module), so a
stage feature no longer edits `report.py`.

## Stop conditions

- A task class leaves the autonomous lane if model precision (ruled items that
  land with no `model-error` fix) stays under ~50% across ~20 ruled items.
  Spec-gap and gate-gap fixes instead flag the planner (`planner_flags`) and the
  gates (`gate_flags`); repeated flags mean fix the release template or add a gate.
- Pause the lane if integrator minutes per landed item exceed the cost of doing
  the work interactively.
- `accepted_unlanded_max` caps WIP: review capacity sets the pace.
