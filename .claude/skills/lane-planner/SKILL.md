---
name: lane-planner
description: Run the interactive planner cycle for lanectl autonomous lanes - re-view candidates and parked items, land trains, classify integrator fixes, write the next WorkReleases, and ratchet acceptance authority. Use when asked to plan, review or feed the lanes.
---

# Lane planner session

A fixed cycle you can enter cold. Judgment-plane only: you write releases,
policy and landings; lanes write code.

## 1. Inputs (read-only)

```sh
lanectl doctor            # home, releases, repos, log, policy, stale attempts, drifted bases
lanectl backlog list --open   # open releases with state and tries (--state, --repo, --json)
lanectl backlog show <id>     # one release: fields, attempts with reasons, outcome
lanectl candidates        # gate-accepted, awaiting integration
lanectl lanes             # routing, limits and live cap usage per lane
lanectl status            # open items and precision (--all includes landed)
lanectl view --html <path>    # management page: backlog, attention, lanes, governance, report
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

```sh
lanectl backlog new <id> --repo <repo> --title "<title>" --scope '<glob>' [--size M] [--class view] [--test <path>]
#   writes backlog/<id>/release.toml (draft = true, base_sha = repo main) and a failing stub test
#   under backlog/<id>/files/<path>; edit the outcome and the test, then:
lanectl backlog publish <id>     # refuses TODO outcomes and stub tests, runs lint-release, clears draft
```

A draft is never ready, so a half-written release in the checkout cannot be claimed (the runner
reads the working tree, not committed main). Rules: after any seed/runner change lands,
`lanectl backlog rebase --pending` moves waiting releases to current main and bumps `revision`
— stale bases caused the first three spec-gap fixes. Acceptance tests must fail on `base_sha` *for the expected
reason* (missing module/feature, not a contract error in the test itself: use
ids of 2+ chars); run `lanectl lint-release backlog/<id>` before publishing (must print OK; it
flags passes-on-base and spec-gap failures); an import failure at collection hides
fixture bugs below it, so also dry-run the test body against a stub or the expected API; scope globs are explicit; build event fixtures from real events
(`lanectl events --type <type> -n 3`): copy field names and values such as
`provider`, `source` and gate `decision` instead of inventing them (invented
fixtures caused the opencode/opencode-go and parked/candidate spec gaps); if
lint-release is wrong, record the override and its reason in release.toml;
size ≤ M; `data_class = "restricted"` for anything private, credential- or
served-state-bearing (it will never go to an external model). Give the
outcome and acceptance, not an implementation plan. Bump `revision` to reissue
a parked item. Commit releases to lanectl main.

## 4. Ratchet

Promote or demote task classes between manual review and rule-based acceptance
by their **model precision** (`MPREC` in `lanectl report`): only `model-error` fixes
count against the model. Spec-gap fixes are planner errors (`planner_flags`: fix the
release template); gate-gap fixes are gate errors (`gate_flags`: add a gate rule).
Raw `PREC` measures the whole pipeline. Classify honestly: if the worker got it wrong,
it is `model-error` even when a gate could have caught it. This decision stays with the operator.

## 5. Run

```sh
lanectl run --max 3        # one lane worker, sequential; start up to caps.concurrency in parallel
```

Release the runner after landing governance, runner or contract changes, and before
running any main-branch command that writes a new event type: an older runner
refuses a log it cannot validate (crashed two workers 2026-11-08). Keep forbidden
patterns (`# noqa`, skip markers) out of acceptance tests: lanes copy them.
In fan-out repos, `acceptance.exec` runs only the acceptance file: gates run in a
user-namespace sandbox where root-owned paths appear as uid 65534 (sovite's ownership
checks fail there); the full suite runs as the train check, unsandboxed, after review.
Release the runner after landing governance or runner changes:
`git tag vX.Y.Z && uv tool install --force git+file:///projects/dev/lanectl@vX.Y.Z`.

## 6. Close

Record the session: candidates landed, fix classes, precision, cost/elapsed,
and what changed in policy.
