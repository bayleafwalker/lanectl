---
name: lane-integrator
description: Run the integrator cycle for lanectl lanes - review candidates and parked review-required attempts, approve or reject them, build trains, plan the landing in shadow, land or requeue, apply in-budget fix commits, triage failed trains and clean up branches and worktrees. Use when asked to integrate, review, train, plan a landing or land lane work.
---

# Lane integrator session

Judgment plane. You rule on gate-accepted work; lanes write code. Stage 4 runs
you in shadow: `plan-landing` records the plan, the operator still lands until
the authority file says otherwise.

## 1. Inputs

```sh
lanectl status                      # states, precision; parked rows show their reason
lanectl candidates                  # gate-accepted, awaiting integration
lanectl events --type item.parked -n 20   # parked review-required attempts
lanectl events --item <item_id>     # one item's full history
lanectl report                      # precision, MPREC, fix classes, landing_shadow
```

Read `governance/integrator.toml` once per session: `autonomous_classes` (empty
= every plan is advisory), `fix_budget_lines`, `allowed_fix_classes`.

## 2. Review a candidate or parked attempt

```sh
git -C <repo> log --oneline <base_sha>..lane/<attempt_id>
git -C <repo> diff <base_sha>..lane/<attempt_id>
git -C <repo> show <base_sha>:<path>     # compare, not just the diff
```

Check: outcome met, acceptance test untouched, no scope escape, no protected path, no test deletion or skip markers, coherent commits. Then:

```sh
lanectl approve <attempt_id> "<what you reviewed and why it is acceptable>"
lanectl reject <attempt_id> "<reason>"          # requeue to the lane
lanectl reject <attempt_id> "<reason>" --park   # park: needs a person or release revision
```

Approved parked items join the candidate pool. Wrong work is requeued, not fixed.

## 3. Train and shadow plan

```sh
lanectl train <repo>                     # all candidates for the repo
lanectl train <repo> --only <attempt_id> # subset
lanectl plan-landing <train_id> --record # shadow plan first; always --record
```

`train` merges candidates on `train/<train_id>` in `<worktree_root>/<train_id>`
and runs the repo check. `plan-landing` prints one action per attempt
(`land`/`hold`/`reject`); never land against a plan you have not read.

## 4. Integrator fixes (bounded)

Fix only on the train worktree, one commit per attempt and per cause, never
folded into the worker's commit:

```sh
cd <worktree>
# fix(<attempt_id>): [spec-gap] <what>
# fix(<attempt_id>): [model-error] <what>
# fix(<attempt_id>): [gate-gap] <what>
git commit -m "fix(<attempt_id>): [<fix_class>] <what> and why>"
<repo check_cmd>                         # re-run the train check before landing
```

Budget from `governance/integrator.toml`: `fix_budget_lines` (default 30,
added + deleted) and `allowed_fix_classes` (default `spec-gap`, `gate-gap`).
Beyond either — too large, or a class such as `model-error` that is not
allowed — do not fix: `lanectl reject <attempt_id> "<reason>"` to requeue, and
leave the class on record for the planner to ratchet.

## 5. Land or reject the train

```sh
lanectl land <train_id>       # fast-forward main; records item.landed + integrator.fix
lanectl reject <attempt_id> "<reason>"   # per attempt that must not land
```

`land` refuses if main moved since the train was built: rebuild the train.
Landing records fixes it finds on the train log, so the titles above are the
contract.

## 6. Failed train

```sh
lanectl triage scan --record   # once per failed train; emits deduplicated proposals
lanectl triage                 # open proposals, with counts
```

Triage before touching the train again: the proposals name the failing node
ids, and a repeat failure usually means a release or gate fix, not another pass.
Do not requeue the same item blindly.

## 7. Cleanup after landing

`lanectl land` removes the train and attempt worktrees; branches remain:

```sh
git -C <repo> worktree list
git -C <repo> branch -d train/<train_id>
git -C <repo> branch -D lane/<attempt_id>   # only once the attempt is landed or rejected
git -C <repo> worktree prune
```

Delete a `lane/*` branch only when its tip is in main or the attempt was
rejected and is not being revised. Check `git -C <repo> log main..lane/<id>` is
empty before `-d`; never force-delete unmerged work silently.

## 8. Close

```sh
lanectl status && lanectl report
```

Record: trains landed, items requeued or parked and why, fix commits by class
and size against the budget, triage proposals opened, and whether the shadow
plan matched what you actually did.
