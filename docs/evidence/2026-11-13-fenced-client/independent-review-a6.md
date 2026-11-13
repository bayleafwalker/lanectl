**PASS for this source snapshot (SHA256 `72c29206…a332f`). I found no new blocking defect, and B1 and B2 are discharged on the evidence below.** I read the source and the frozen tests with Read and Grep only. I did not run any of the tests, so "the frozen tests pass" comes from your brief, not from me.

## B1: discharged

- **Fix** (`fenced_train.py:219-231`): `_wait_terminal` now returns True only when `state in TERMINAL and os.path.lexists(receipt)`. It polls until `timeout + WAIT_MARGIN_S` and has no short-grace exit. `RECEIPT_GRACE_S` is still defined (`:28`) but nothing uses it. That is harmless dead state, and the comment at `:26-27` says so.
- **Deadline path** (`:100-106`):
  - A False return goes to `_stop_terminal`, which runs `systemctl stop <exact unit>` and polls for a terminal state for up to `STOP_WAIT_S`.
  - If termination is proven, `terminal=True` and cleanup runs.
  - If it is not proven, `keep=True` and the error names the orphan and its directory (`:103-104`, `:148-149`).
  - The `except FenceError` and `except Exception` handlers skip a second stop when `keep` or `terminal` is already set (`:136`, `:141`).
- **Interruption** (`:118-134`) is unchanged. `started and not terminal` triggers a stop, a failed stop keeps the orphan, and cleanup failures are reported.
- **Queued start:** a queued unit reads `inactive`, and with no receipt it is not terminal. `systemctl stop` replaces a queued start job, so the deadline stop also covers a train that has not started yet.
- **Forged success:** nothing here makes one easier. Receipt trust, digest binding and the `_read_receipt` checks are untouched. The receipt is now required before `_read_receipt` runs, so the `missing after the unit became…` failure at `:280` can only occur in a narrow race after the wait.

## B2: discharged

- **Test evidence:** `test_stage_accepts_train_and_historical_linked_worktrees` (`test_acc_fenced_train_pending.py:31`) uses real `git worktree add`, with a branch variant and a detached variant. Your brief says it passes on both the old and corrected source, so `_stage` was not the defect. That test is the evidence that `_stage` works from linked worktrees.
- **Diff scope:** I did not diff against the seed. I am relying on your brief that the diff is limited to the B1 change.

## New defects: none blocking

Non-blocking observations on this change:

1. **Slow failure when no receipt is written.** If a unit fails before the root prepare step publishes any receipt, the client now waits the full `timeout + 180s`, which is 1980s at the default 1800s timeout. Before, it waited about 20s. The result is still a failed train with cleanup, so it is a cost in time and not a safety problem.
   - Trigger: the unit reaches `failed` and no receipt is ever written.
   - Contract `:156-158` says rejection records a root receipt, so this should be rare.
   - It is the cost of the "wait for both" rule in contract step 7 (`:61-63`), so I would accept it and note it in the closeout.
2. **`_stop_terminal` accepts a bare `inactive`** (`:244`), and ignores the `stop` return code (`:238-241`).
   - Trigger: `stop` fails or times out while a start job is still queued and unrelated to the stop, so the unit reads `inactive` and is wrongly counted as proven stopped.
   - This predates the change and has the same root as B1. It is now reachable only after a 180s-plus margin of observed non-completion.
   - Hardening: require `stop` to return 0, or two consecutive terminal reads. Advisory only.
3. **Redundant `terminal = False` at `:99`.** Harmless.

## Kept separate and unchanged

- The accepted shared-UID and sibling `/proc` exposure.
- Open network.
- Dependence on root-owned ancestors of `/var/lib/lanectl-train`.
- The earlier advisories A1 to A6.
- Behaviour against the real systemd unit: `inactive` timing, handback timing, the 600s stop limits and the host's Git version are all still unproven. The fake-`systemctl` tests show client logic only.

## Integration prerequisites

These are not claimed by this review:
- the worker actually finishing
- the final artifact matching the hash byte for byte
- the repository gates passing
- live-host qualification

**Verdict: PASS for this source snapshot.**
