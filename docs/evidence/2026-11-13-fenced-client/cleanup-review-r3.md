**PASS**

I found no blocking regressions. I read the code and tests only and ran nothing. I did not recompute the `runner.py` hash. The snapshot says commit `dc70775a…` and sha256 `a050a1c8…`.

## R2 blocker (shared worktree root): closed
- `_managed_container` (`runner.py:410-422`) compares `Path(path).resolve()` with `Path(worktree_root).resolve()`.
  - Exact equality and symlink aliases are both caught, and the layout doesn't matter.
  - The root can be inside canonical, outside it, or equal to or above it. The last case is also refused earlier by `_contains_canonical`.
- `_discard` (`runner.py:440-451`) and `_historical_checkout` (`runner.py:796-810`) both run this guard before any `git worktree remove`, `rmtree` or yielding a checkout.
  - In `_historical_checkout` the protected checkout is replaced by a scratch worktree under a temp dir. The scratch discard passes all three guards.
- I traced all eight frozen cases (inside/outside × alias/direct × discard/historical) in `test_acc_train_cleanup_container.py`.
  - Each target is refused, or replaced by scratch.
  - For the `inside` layout, `_unmanaged_canonical` correctly returns False for `target == root`, so `_managed_container` is the guard that catches it. R2's B1 was in exactly that gap.
  - The `outside` layout is stopped only by `_managed_container`.
  - In the discard cases `rmtree` is never invoked. In the historical cases the yielded path is neither the root nor an ancestor of it.
  - The sibling's `must-survive` file therefore stays.
- Individual descendants still work. `_unmanaged_canonical` exempts targets strictly below an inside root, and `test_explicit_managed_checkout_inside_canonical_can_still_be_cleaned` covers this. Outside-canonical descendants pass every guard.

## Preserved requirements
- **Canonical protection:** `.git`, `src`, the canonical root, its ancestors and their aliases are still refused through `_contains_canonical` and `_unmanaged_canonical`, which resolve paths without consulting Git config.
- **Historical overlap:** it is still reconstructed in scratch, and the exact-tip and clean-status checks apply to whichever checkout is yielded. I did not see these checks weakened, but I did not re-read them at `runner.py:~883`.
- **Land cleanup (`runner.py:974-986`):**
  - It runs after the landing and effects are recorded.
  - Each target is discarded independently.
  - A refusal (`ValueError` or `RuntimeError`) becomes a notice in the result string.
  - Other safe targets are still cleaned.
  - The `startswith("landed")` contract holds.
- **Coverage advisory from R2 (the earlier non-blocking note on missing coverage):** closed. `test_completed_historical_land_survives_refused_canonical_cleanup` creates `<worktree_root>/cleanup-history-a1` and asserts it is gone after canonical cleanup is refused.
- **Scope:** I only reviewed `runner.py`, per the brief.

## Advisories (non-blocking, bounded)
1. **Ancestors of the container outside canonical:** a recorded worktree that is a strict ancestor of an outside-canonical `worktree_root` is not caught. Its resolved path contains the root but not canonical, and it isn't equal to the root.
   - Example: a recorded path of `tmp_path` with the root at `tmp_path/managed`.
   - `_discard` would delete every sibling.
   - This is outside the declared "exact equality and alias" boundary and is the same class as R2 advisory 5, a recorded path outside canonical.
   - A one-line extension would be to also test `root.is_relative_to(target)` in `_managed_container`. I'd consider it, but it isn't required.
2. **Refusal visibility:** a refused cleanup is only reported in the return string. There is no durable event, and a retry returns "already recorded", so a leaked worktree is never revisited. This is unchanged from R2 advisory 2.
3. **Other `_discard` callers (`runner.py:552, 657`):** they still propagate `ValueError`. The call at `:657` runs after the decision is recorded, so a misconfigured root there would surface as an exception. This is unchanged from R2 and only reachable with a misconfigured root.
4. **TOCTOU** between the guard and `rmtree`: unchanged, low risk.
5. **Setup in scratch worktrees:** `setup_cmd` runs in a fresh scratch worktree. A legacy train with a pre-built environment can fail the recheck, which fails safe.

## Not established
This review doesn't establish that the tests pass, native gates, the exact-tip train, final artifact/byte equality with the reviewed bytes, or hosted qualification.

**PASS**
