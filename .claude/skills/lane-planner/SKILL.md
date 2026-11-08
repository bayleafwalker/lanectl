---
name: lane-planner
description: Run the interactive planner cycle for lanectl autonomous lanes - re-view candidates and parked items, land trains, classify integrator fixes, write the next WorkReleases, and ratchet acceptance authority. Use when asked to plan, review or feed the lanes.
---

# Lane planner session

A fixed cycle you can enter cold. Judgment-plane only: you write releases,
policy and landings; lanes write code.

## 1. Inputs (read-only)

```sh
lanectl status            # states, precision, per-model results
lanectl candidates        # gate-accepted, awaiting integration
lanectl ready             # Definition-of-Ready blockers per release
lanectl events --item <id>   # one item's history
```

## 2. Re-view

For each candidate, read `git -C <repo> diff <seed_sha>..lane/<attempt>`.
- Good: `lanectl train <repo>` → inspect → `lanectl land <train_id>`.
- Small fix needed: commit on the train worktree as
  `fix(<attempt_id>): [spec-gap|model-error|gate-gap] <what>`, re-run the
  repo check, then land. Never fold fixes into the worker's commit.
- Wrong: `lanectl reject <attempt_id> "<reason>"` (requeue) or `--park`.

For each parked item, read the reason. Protected-path parks need your review
of the diff; escalations usually mean the release is underspecified: revise it.

Classify every fix and park: spec-gap → improve the release template;
model-error → routing/prompt (LaneRevision); gate-gap → a new gate rule.

## 3. Re-plan

Write the next releases from the current stage of
`docs/adr/0001-autonomous-lanes.md`. One directory per item:

```
backlog/<id>/release.toml       # see existing items for the shape
backlog/<id>/files/<repo-path>  # planner-owned acceptance tests
```

Rules: after any seed/runner change lands, rebase pending releases (set
`base_sha` to current main and bump `revision`) — stale bases caused the first
three spec-gap fixes. Acceptance tests must fail on `base_sha` *for the expected
reason* (missing module/feature, not a contract error in the test itself: use
ids of 2+ chars); run `uv run pytest <acceptance file>` on base before publishing; an import failure at collection hides
fixture bugs below it, so also dry-run the test body against a stub or the expected API; scope globs are explicit;
size ≤ M; `data_class = "restricted"` for anything private, credential- or
served-state-bearing (it will never go to an external model). Give the
outcome and acceptance, not an implementation plan. Bump `revision` to reissue
a parked item. Commit releases to lanectl main.

## 4. Ratchet

Promote or demote task classes between manual review and rule-based acceptance
by their precision in `lanectl status`. This decision stays with the operator.

## 5. Run

```sh
lanectl run --max 3        # one lane worker, sequential; start up to caps.concurrency in parallel
```

Release the runner after landing governance or runner changes:
`git tag vX.Y.Z && uv tool install --force git+file:///projects/dev/lanectl@vX.Y.Z`.

## 6. Close

Record the session: candidates landed, fix classes, precision, cost/elapsed,
and what changed in policy.
