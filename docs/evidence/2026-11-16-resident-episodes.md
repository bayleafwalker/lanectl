# Resident episode implementation evidence — 2026-11-16

## Scope and status

This change adds the `lanectl resident` plugin, its additive event contracts,
an exec gate, a disabled example profile and a commissioning runbook. It runs
one bounded logical episode under the existing execution owner. It does not
implement a persistent native Goal, own Sprintctl work, schedule another
episode, publish external effects or modify WorkRelease acceptance gates.

Base revision: `a264b5bd07692b32bb5373b4d741f15331777388`.
Validation runtime: Python 3.13.5, runtime dependencies unchanged (stdlib only).
The source is reviewable; no native route, provider credential boundary, host
deployment or canonical landing is qualified by this evidence.

The pilot accepts only the exact local durable `lanectl.events.EventLog` on
one protected host. Remote or buffered backends are refused, with no local
fallback for a selected served authority. Sprintctl remains the real work
owner. Qualification/profile/source-check protection and OS containment belong
to the external host owner.

## Tests and review

The new module began with failing tests before implementation. Later review
found concrete lifecycle and transport defects. Nineteen additional negative
regressions were observed failing before fixes were applied:

- partial object publication after a failed fsync;
- a generation fence between durable started evidence and the exec gate;
- unknown process cleanup incorrectly freed after fencing;
- signalling after an observed PID birth-identity mismatch;
- accepting unsupported buffered event-log implementations;
- malformed mandatory context, budget metadata and diagnostic sections.

The corrected focused command passed **71 tests in 12.49 seconds**:

```sh
uv run pytest -q tests/resident/test_resident.py \
  tests/stage1/test_acc_event_properties.py \
  tests/stage1/test_acc_plugin_discovery.py \
  tests/stage1/test_plugin_discovery_extra.py
```

These include real credential-free child execution, bounded timeout, killed
coordinator recovery, ordinary descendant cleanup, immutable artifact bytes,
duplicate wakes, concurrency, stale generations, gate durability, source
freshness, schema/scope/reference validation, symlink refusal and inherited
credential-environment refusal. Only the protected-file ownership probe is
emulated in the fixture; these tests do not qualify an OS or native provider
route.

A separate read-only reviewer reread the scoped corrections and found no
remaining blocker in that review scope. The review verified that a durable
started transaction completes before the separate final generation/freshness
check and gate release; fencing takes the same local event-log lock.

## Cross-repository packet compatibility

A direct smoke check imported the actual sibling AgentOps
`scripts/resident_context.py` implementation and used `build_context` to emit a
ready packet with a required source, source-backed disputed memory, orientation
and an explicit omission. AgentOps `verify_context_packet` and lanectl
`_validate_context` both accepted it. The result contained one exact source
reference and one omission. The AgentOps checkout at that check was
`f287790817ee6b0cdf3d84d5e2229cf6b01fe745`.

This proves compatibility of that emitted packet with this consumer, not
source-owner availability or currentness on a deployed host. The protected
admission source-recheck receipt remains required by default, has a maximum
60-second validity window and is rechecked at the final exec gate.

## Required full-suite gate

The final `uv run pytest -q` result was **1,209 passed and 70 failed** in
164.29 seconds. All new resident tests and the event/property/plugin tests
passed in that run; the full repository gate did not pass.

Earlier full-suite validation reached **1,190 passed and 70 failed** in
172.52 seconds. The environment cannot reach the systemd user bus. Two
representative failures were reproduced on a clean detached worktree of the
unchanged base revision, with no resident files or contract changes:

```sh
uv run pytest -q \
  tests/seed/test_sandbox.py::test_systemd_sandbox_blocks_writes_outside_checkout \
  tests/seed/test_end_to_end.py::test_good_item_reaches_candidate_and_lands
```

Both failed in 0.56 seconds with the same underlying diagnostic:

```text
Failed to connect to user scope bus via local transport: Operation not permitted
```

The sandbox test cannot launch its sandbox; the end-to-end test consequently
records acceptance failure instead of a candidate. This is representative
baseline reproduction, not an independent classification of every full-suite
failure. No sandbox test was skipped or weakened, and no protected sandbox or
governance implementation was edited.

`AGENTS.md` requires `uv run pytest -q` to pass. That required gate remains
unsatisfied in this environment. The implementation is being retained as a
draft for review under the session's explicit instruction to preserve that
gate, not merged or declared commissioned. Run the complete suite on the
required systemd-capable host before merging or enabling a real profile.

## Host qualification still required

The disabled example profile must remain disabled until the external owner
has tested the actual immutable launcher, native runtime/tool availability,
subscription/API credential separation, direct API/database denial, egress
including IPv6, hard aggregate inference/resource limits, full process-tree
containment, source-owner admission checks and backup/restore. The launcher
must not place native authentication caches or raw memory-store credentials
inside the tool process's accessible workspace.

Unknown cleanup keeps the active slot occupied across fencing. A new wake
cannot bypass it. Checkpoints and continuation are observations for the next
owner-admitted episode, never work completion or an external-effect grant.
See `docs/resident-episodes.md` for the concrete interface and recovery path.
