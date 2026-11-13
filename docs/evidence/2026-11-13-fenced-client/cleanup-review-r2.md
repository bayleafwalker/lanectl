**HOLD.** One blocker, with a one-line fix. Nothing was executed, including the tests, and I did not verify the snapshot hash `be20b2ed…49ba` against `runner.py`.

## Blocker

**B1. The managed worktree root itself is treated as a safe target (`runner.py:419-422`, used by `_discard` at 430 and `_historical_checkout` at 782).**
- `_unmanaged_canonical` returns False for any target for which `target.is_relative_to(root)` is true. That includes `target == root`.
- Trigger: `worktree_root` is configured strictly inside canonical, for example `canonical/.worktrees`. A recorded `train.built["worktree"]` equals that root. The record is worker-influenced, which is the premise of this whole change.
- Cleanup effect: `land` at `runner.py:960` calls `_discard(repo, Path(d["worktree"]))`. The call passes both guards and `shutil.rmtree`s the whole root. That deletes every other in-flight attempt and train worktree, not just the recorded one. Nothing in canonical is lost, but it breaks the managed/unmanaged boundary the change is meant to enforce.
- Historical effect: `_historical_checkout` yields the root itself as the checkout, so candidate checks get a writable sandbox over every sibling worktree.
  - This is reachable when `git rev-parse HEAD` run from the root resolves to canonical's HEAD and that equals `tip`, which holds for a train that is already at main.
  - The `status --porcelain` check passes on a clean canonical.
- Fix: in `_unmanaged_canonical`, treat `target == root` as protected. Equivalently, require the target to be strictly below the root: `not target.is_relative_to(root) or target == root`.
- The same line also gives the historical path reconstruction for free, because `_historical_checkout` already uses `_unmanaged_canonical`.
- Missing test: none of the frozen tests puts the root itself, or a root alias, as the target. Add one case to `test_acc_train_cleanup_recovery.py` for `_discard` and one for `_historical_checkout`.

## What I checked and found sound

- **`_contains_canonical` (383-392):** it is pure resolved-path arithmetic and covers equal, ancestor and alias. No Git config or hook can influence it.
- **`_managed_worktree_root` (395-407):** a root equal to or above canonical returns `None`, so every in-canonical target is unmanaged. That includes `worktree_root == canonical`, where cleanup is refused and the worktree leaks. The spec accepts that outcome.
- **`_unmanaged_canonical` (410-422):** `.git`, `src` and aliases to them (resolved before comparison) are refused. Subpaths strictly inside a strict-inside root are still cleanable. This closes R1 advisory 3.
- **`_discard` (425-434):** both guards run before `git worktree remove`, `rmtree` and `prune`. That also fixes R1's gap where `.git` or `src` passed the old guard.
- **`_historical_checkout` (780-792):**
  - A protected checkout is reconstructed with `git worktree add --detach <tempdir>/checkout <tip>`. The scratch path can never overlap canonical, so the final `_discard` of the scratch is safe.
  - An unprotected checkout, including one under a strictly-inside managed root, is used as before. Real recovery is preserved.
  - The exact-tip checks at `runner.py:883-889` (`HEAD == tip`, clean status, and re-verified after the checks) still run on whichever checkout is yielded. The reconstruction therefore doesn't weaken the exact-tip boundary.
  - This closes R1 advisory 2.
- **`land` cleanup (956-968):**
  - The landing is already committed and recorded before cleanup starts.
  - Each target is attempted independently. `ValueError` and `RuntimeError` become a notice in the result string, and landing stays a success.
  - This closes R1 advisory 1.
  - I found no caller that parses the result string beyond `startswith("landed")`.
- **Other `_discard` callers (`runner.py:552, 657`):**
  - `552` runs before the work starts, so a refusal there fails safe.
  - `657` runs after the decision is recorded, and a refusal there would propagate. It is only reachable with a misconfigured `worktree_root`, so I treat it as an advisory.

## Advisories

1. **`test_completed_historical_land_survives_refused_canonical_cleanup` doesn't check cleanup of other targets.** It asserts landing success and canonical intact, but not that the other safe attempt directories were still discarded after the refusal. This is the "continue cleanup of other safe attempts" requirement, so add a spy on `_discard` or a synthetic second attempt directory.
2. **A refused cleanup is only reported in the return string.** No log event records it, and a retry returns "already recorded", so the leaked worktree is never revisited. A durable event would make it findable. This is optional.
3. **Reconstruction runs `setup_cmd` in a fresh scratch worktree.** A legacy train whose original checkout had a pre-built environment can fail the recheck with "failed recheck; not landing". It fails safe and matches `build_train`, so it is only worth documenting.
4. **TOCTOU between the guard and `rmtree`.** This is the same low risk as in R1 and is unchanged.
5. **Unchanged from R1 and out of scope here:** recorded paths outside canonical, such as an arbitrary directory outside `worktree_root`, are still discardable. That was not part of the refined boundary.

## Verdict

**HOLD** until B1 is fixed and covered by a test. After that, I expect the delta to meet the refined boundary: canonical data preserved, historical recovery working, and a truthful landing record. This review does not establish native completion, gates, the exact-tip train or hosted owner qualification.
