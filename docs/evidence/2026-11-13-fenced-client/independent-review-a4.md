I've finished reading the source and tests, and I'm writing up the verdict now. I didn't run anything.

# Review of lanectl fenced train client at `2cfa660`

**Verdict: HOLD for source integration.** The three flaws root reproduced are fixed, and I found no way to forge a pass. But I found one deviation from the host contract (B1) and one coverage gap on the main product paths (B2). Both are cheap to fix.

## What I checked and found sound
- **Receipt trust** (`fenced_train.py:263-304`, `receipt_returncode` at `:42-67`):
  - The receipt directory is opened `O_NOFOLLOW` and must be root-owned without group/other write.
  - The receipt is opened fd-relative with `O_NOFOLLOW`, then checked for regular file, root owner, no group/other write, and a size cap.
  - Success needs `handed_back`, the train id, the digest of the exact request bytes, and the full success tuple. Anything else maps to a nonzero code, including `handed_back=false` with exit 0.
- **No environment fallback:** `runner.py:705-708` dispatches `systemd` straight to `run_command`. An invalid value fails in `config.py:94-97`. The in-tree `result.json` is never read.
- **Request freshness:** each submission gets a new train id and a new 128-bit nonce, and both are bound by the digest.
- **The three fixed flaws:**
  - `_open_parent` walks directories with `O_NOFOLLOW` and `dir_fd`.
  - Leaf files are opened `O_NONBLOCK` and then checked with `fstat`.
  - `_read_head` uses the same walk. A FIFO HEAD returns False, and I see no blocking path left.
- **Cleanup:** `_remove` runs only after a terminal state is established. `keep` retains the directory and names the unit on a failed stop or `KeyboardInterrupt`. The uncertain-start test covers this.
- **Admission and doctor:** `runner.py:275,438`, `doctor.py:121` and `doctor.py:133-152` accept `systemd` consistently, and `systemd` is not treated as unfenced.

## Blocking

**B1. Terminal state is accepted without the receipt, so a stale `inactive` reading can abandon a live train.**
- Where: `fenced_train.py:217-227`, then `:105-106` and `:149-154`.
- Contract: host-contract step 7 says to wait for the receipt **and** `inactive`/`failed`. The client treats `inactive` alone as terminal and gives the receipt only 20s (`RECEIPT_GRACE_S`).
- Why it matters: `systemctl start --no-block` returns once the job is queued. As I understand systemd, a unit with a queued start job, or one waiting on ordering, still shows `ActiveState=inactive`. I have not observed this on the host, so how often it happens is unproven.
- Trigger: use a fake `systemctl` where `start` returns 0 and `show` reports `inactive` for the first poll or two, then `active`, with the receipt written at the end of a train that takes longer than 20s.
- Result:
  - The first poll counts as terminal.
  - After 20s the receipt is missing, so `_read_receipt` raises `FenceError`.
  - `terminal` is already True, so `_stop_terminal` is skipped.
  - `_remove(train_dir)` then runs against a unit that may be live or about to start.
- Consequences: no false pass is possible, so this is not an integrity break. But it can fail a good run spuriously, and it can leave an unstopped, unnamed train running after cleanup is attempted. That conflicts with "unknown liveness must retain a named orphan".
- Why the tests miss it: the fake `show` (`test_fenced_train.py:60-61`) is `inactive` from the start and the receipt is written inside `start`.
- Fix: loop until the receipt exists (`lexists`) **and** the state is terminal, up to the existing deadline. On deadline, go through `_stop_terminal`. The finish step publishes the receipt before the unit goes inactive, so this costs nothing on the normal path. Add a test for stale-inactive followed by a late receipt.

**B2. No test passes a linked worktree to `run_command`, and `build_train`, `recheck_train` and `_historical_checkout` all pass one.**
- Where: `runner.py:753`, `:738` and the recheck path at `:1021` onward all produce `git worktree add` checkouts. The tests only stage plain `git init` repos (`git_repo` at `test_fenced_train.py:89`), and the string "worktree" appears in none of the four test files.
- What I couldn't verify: I can't tell, without running it, whether `git clone --local --no-hardlinks <linked worktree>` works. A linked worktree's `.git` is a gitfile pointing at `.git/worktrees/x`. Only the lane-attempt clone at `runner.py:510` is made self-contained for `systemd` mode, and its train result is discarded anyway (see A2).
- Why it blocks: the stated outcome covers the setup, check, recheck and historical paths. Those are exactly the paths that go through `build_train`, and nothing shows `_stage` works from them.
- Failure mode: it should fail closed, but it could mean every `systemd` train fails.
- Fix: add one `_stage` test from a `git worktree add` source, including a detached historical one. Check that the `rev-parse --git-common-dir` and alternates logic at `:348-351` holds there.

## Advisories
- **A1. Candidate-controlled `.git` is read by Git.**
  - `_stage` runs `rev-parse` and `clone --local` against a worker-written checkout. `-c core.hooksPath` and `core.fsmonitor` are overridden, and global and system config are off. I see no command-execution path.
  - The existing test only covers filters in the source config, which are not copied. It does not cover a `.git` gitfile redirect, `.git/objects` symlinks or a hostile `commondir`.
  - Whether `clone --local` dereferences or refuses symlinks under `objects/` depends on the Git version. I haven't verified it, so I'm treating it as unproven.
  - Cheap hardening: before cloning, `lstat`-walk `objects/` and refuse symlinks. Require that `.git` is a real directory or an expected gitfile.
- **A2. `runner.py:534` ignores the result and `wt` is unchanged for `systemd` mode.**
  - The train runs on a discarded copy, so this call costs a train run and has no effect on `wt`. That is consistent with "no copyback", but it is worth removing or documenting.
- **A3. Setup now runs more than once per outcome.**
  - `_request` prepends setup to the check command. `build_train` and `recheck_train` also run setup separately first.
  - That is correct for no-copyback, but it is wasteful.
  - The `set -e` prefix (`:311`) also changes check semantics, for example `a; b` or `x || true` patterns. The test at `:118` pins the prefix.
  - Confirm the prefix is intended.
- **A4. Staged `HEAD` is not compared with an expected tip.**
  - `commit` is taken from whatever the checkout's HEAD is. Callers verify the tip in some paths, such as `recheck_train` and `land`, but `run_command` doesn't enforce it.
  - Uncommitted changes are ignored, because only HEAD is staged.
  - Consider an optional `expect_sha` argument.
- **A5. Doctor checks presence only.**
  - `check_train_service` confirms `lanectl-train@.service` exists. It does not check the spool and receipt directories, or their ownership, which the client itself requires at `:84` and `:270`.
- **A6. `rmtree` after `handed_back=false`.**
  - Cleanup tries `rmtree` on a train-owned tree. It fails and is reported, which is acceptable. The error message could name the contract's operator recovery (`chown`).

## Bounded residuals and unproven claims
- **Accepted by your brief, not findings:**
  - the shared `lanectl-train` UID and sibling `/proc` exposure
  - open network
  - receipt authority depending on root-owned `/var/lib/lanectl-train` ancestors, which is a host-side precondition
- **Unproven:** all behaviour against the real `systemd` unit. That includes the `inactive` timing in B1, handback timing, the 600s limits, and Git behaviour on the host's version. The fake `systemctl` tests show client logic only.
- **Not claimed:** field proof, full fenced repository qualification, or my independent re-run of the 10 tests.

**HOLD** for source integration until B1 and B2 are fixed, with tests. Live-host qualification remains required either way.
