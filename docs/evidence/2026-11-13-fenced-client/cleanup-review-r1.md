**Verdict: PASS for source snapshot `runner_sha256` 5cffc082…049b, with advisories.** I found no blocking regression against the stated outcome. This is a read-only review. I did not verify the file hash, and nothing was executed, including the tests. The guard is not integrated.

**What I checked**

- **Path resolution (`_contains_canonical`, `runner.py:383-392`).** It checks `canonical.resolve().is_relative_to(path.resolve())`.
  - It catches an exact match, any ancestor, and a symlink alias to either, including an alias to an ancestor.
  - It is pure path arithmetic, so no Git config or hook can influence it.
  - It also works when the path does not exist, because `resolve()` is non-strict.
- **Order of operations (`_discard`, `runner.py:395-402`).** The guard runs before `git worktree remove`, `rmtree` and `prune`. That closes the base defect where Git refused and `rmtree` ran anyway.
- **Ordinary cleanup.**
  - Independent attempt, train and scratch paths are not ancestors of canonical, so they still run the full remove, rmtree and prune sequence.
  - The `build_train` train worktree is `repo.worktree_root/train_id`. That sits inside canonical only if `worktree_root` is configured under it, and an in-canonical subpath is allowed.
- **Historical scratch.** In `_historical_checkout` (`runner.py:753-759`), the scratch is a fresh tempdir under `lanectl-historical-train-*`. It can never contain canonical, so its cleanup is unaffected.
- **Tests.** `test_acc_train_cleanup_boundary.py` covers root, ancestor and alias, asserting no rmtree, no `worktree remove` and the marker surviving. It also covers an independent checkout still being removed. The checks are sound.

**Advisories, none of which block**

1. **`land` handles the refusal badly (`runner.py:923-925`).** The `ValueError` propagates out of `land` after main was fast-forwarded, `item.landed` and `work.synced` were logged, and deploy teardown ran.
   - The caller sees an exception for a landing that actually succeeded.
   - The per-attempt `_discard` calls at line 925 are skipped, so those worktrees leak.
   - A retry returns "already recorded" at line 835, so the leaked cleanup is never redone.
   - This is safe, since an explicit error is acceptable, but the behavior is wrong.
   - Recommended fix: wrap each post-landing `_discard` in `land` in `try/except ValueError`, so every target is attempted. Return a notice in the result, such as "cleanup refused for X", and keep landing as success.
   - The `_discard` calls at lines 520 and 625 sit inside the coordination wrapper or an attempt flow, and I judged propagation there acceptable. `execute` parks on error.
2. **Historical recovery still runs checks in an ancestor (`runner.py:750`).** `_historical_checkout` only compares `checkout.resolve() != canonical.resolve()`.
   - A recorded checkout that is an ancestor of canonical, or a directory containing it, passes this check and is yielded as the checkout.
   - That gives candidate checks a writable sandbox over a tree that contains canonical, which is the exposure this function exists to prevent.
   - It is only practically reachable if that ancestor is a git tree with `HEAD == tip`, but it is cheap to close.
   - Recommended fix: use `not _contains_canonical(repo, checkout)` there.
3. **Subpaths of canonical are not guarded.** A recorded `d["worktree"]` of `canonical/.git` or `canonical/src` would still pass the guard. Then `git worktree remove --force` and `rmtree` act on it.
   - This is outside the stated outcome, which covers canonical, ancestors and aliases.
   - It matters because that field comes from log records that a worker can influence.
   - Consider refusing any target inside canonical unless it is under the configured `worktree_root`.
4. **Minor TOCTOU.** The check and the `rmtree` are separate steps, so a symlink swap between them is theoretically possible. That is low risk and consistent with the existing design.

For the integration notes: the guard satisfies the stated outcome. Advisory 1 is the one I'd want fixed before or alongside integration, and it is a small change. This snapshot should be integrated only if the final native source matches the stated hash, the actual worker and gates pass, and the exact-tip train passes. None of that is claimed here.
