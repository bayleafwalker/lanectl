**Verdict: PASS.** The stop-acknowledgement defect is discharged, and I found no new blocking correctness or security bug. This is a static read only. I ran nothing and did not run the tests.

## Findings

No blocking findings. Three non-blocking notes:

1. **Defect fix confirmed** (`fenced_train.py:234-251`).
   - Every non-acknowledged stop returns `False` before any `_active` poll. That covers `OSError`, `TimeoutExpired` and a nonzero exit.
   - An inactive reading that might mean a queued start can no longer prove cancellation.
   - Only `returncode == 0` leads to the bounded terminal poll, and that poll still needs `inactive` or `failed`.
   - The stop test (`test_acc_fenced_train_stop.py:7-23`) forces `_active` to return `"inactive"` and asserts the result is true only for `acknowledged`. It also asserts exactly one stop call, so there is no retry or fallback path.

2. **`False` fails closed in all three callers.**
   - The timeout path (`:101-104`) sets `keep` and names the orphan.
   - The `FenceError` and generic `Exception` paths (`:136-144`) set `keep = not terminal`.
   - The `KeyboardInterrupt` path (`:119-127`) sets `keep` and re-raises with the orphan message.
   - When `keep` is set, `_remove` is skipped (`:148-149`), so nothing is cleaned up without acknowledged cancellation.
   - `_stop_terminal` itself raises nothing except an uncaught `KeyboardInterrupt` inside `subprocess.run`. A `KeyboardInterrupt` raised there during the `FenceError` or `Exception` handlers would escape without setting `keep`, but nothing is deleted on that path because the cleanup code is never reached. This is not new in A7.

3. **Residual race, non-blocking and theoretical.** If `_start` itself raises `TimeoutExpired`, the `systemctl` client is killed and a stop is then sent for a unit that may not exist yet. A stop that returns 0 (it still polls terminal) would let the checkout be removed. If the start request were still in flight to systemd and landed after the stop, the unit would run with its directory deleted.
   - It would fail on a missing repo rather than run unfenced, so it is a robustness issue and not an escape.
   - This is the same as before A7 and is not a regression.
   - If you want to harden it later, treat a start timeout as `keep`. That is outside this tiny delta.

## Earlier fixes still hold

- **B1/B2:** `_wait_terminal` (`:219-231`) returns true only when the state is terminal **and** the receipt exists. It runs until the overall `timeout + WAIT_MARGIN_S` deadline and never shortens it.
- **Recovery test:** it still monkeypatches `_stop_terminal` and asserts one start and one stop per run. I only grepped `test_acc_fenced_train_recovery.py` and `test_acc_fenced_train_pending.py`, so I have not confirmed the pending test or the linked-worktree staging coverage.

## Not covered

- Live host behaviour. I did not verify that `systemctl stop` on a queued template unit returns 0 and replaces the pending start job. That is the assumption the fix rests on, and your A7 live probes should exercise it.
- Final A7 live probes, full Sovite parity, native completion and gates, and the artifact-content match remain open, as you said.
- The shared dedicated UID and open network remain accepted residuals.
