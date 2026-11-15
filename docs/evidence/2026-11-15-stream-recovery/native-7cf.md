**CLEAR**

I checked this statically with Read/Grep/Glob only. I ran nothing, so the reported 1217 full and 77 focused passes are unverified by me.

**Guard closes the reported bug.**
- `_closed_wal` (`src/lanectl/stream_recovery.py:475-481`) reads the first 20 bytes of the closed private candidate. It requires the 16-byte magic `SQLite format 3\0` and `header[18:20] == b"\x02\x02"`. Bytes 18 and 19 are the write and read format versions, and both are 2 in a WAL database.
- The fault wrapper switches the file back to DELETE. That leaves no sidecars, passes the immutable inspection, and keeps the logical row digest unchanged. Before this change nothing caught it, so the old receipt carried a hard-coded `journal_mode: "wal"` (`:647`) that was false. The new guard refuses it.
- The guard is a plain `open("rb")`. It doesn't open SQLite and creates no `-wal`, `-shm` or `-journal` files.

**Ordering is correct** (`:759-778`).
1. `_prepare_wal` runs.
2. Sidecar check.
3. Immutable inspection.
4. Sidecar check again.
5. Logical row digest.
6. `_closed_wal` (`:770`).
7. `_hash`, `_sync_file`, `_same_input`, `_fresh`, `_link`, `_sync_parent`, `_check_publication`.

The guard runs before hashing, fsync and the exclusive `_link`. A refusal therefore publishes nothing and returns no receipt. Every connection that runs between `_prepare_wal` and the guard is read-only (`_connect` uses `mode=ro`, and the digest uses `immutable=1`). None of them can change the header after the guard. The file's hash is taken immediately after the guard, so the hashed bytes are the ones checked.

**No regressions seen.**
- `RecoveryError` is already caught and re-raised in the `restore` handler (`:782-795`), so the refusal is structured, with `published=None`.
- The change doesn't touch `_new_file` private permissions, the `_fresh` and `_link` no-overwrite behaviour, `_check_publication` inode handling, or `_stage` cleanup.
- Exact full-row preservation is still enforced by the existing digest comparison at `:768`.
- A truncated or short file fails the header comparison and is refused. A valid WAL candidate passes.

**Regression test** (`tests/stage9/test_stream_recovery.py:1104-1128`)
- It uses a real SQLite database. The wrapper calls the real `_prepare_wal`, then runs `PRAGMA journal_mode=DELETE` through sqlite3 and asserts it returns `("delete",)`.
- It records the header after that switch and asserts magic plus `\x01\x01`. This proves the fault really produced a DELETE-mode file, so the test can't pass vacuously.
- It requires `RecoveryError` matching `closed-candidate-not-wal`, so the refusal comes from the new guard and not some earlier check.
- It asserts the destination doesn't exist, the artifact bytes are unchanged, and the source rows are unchanged. That covers refusal, no publication, and no source or artifact mutation.
- Nonblocking: it doesn't assert that the staging directory is cleaned up. That behaviour is pre-existing and covered by the existing `_stage` handling.
- Nonblocking: it doesn't separately test a bad magic or a mixed header such as `\x01\x02`. The single comparison covers both.

**Product and storage intention.** The change stays inside local restore verification. It makes the existing `journal_mode: "wal"` receipt claim true, and it adds no hosted custody, retention or RPO claim, rollout, or authority cutover. `authority_changed` stays `False` in the binding and the receipt. The 300s online-copy-phase timeout at `:436` is unchanged and is not a global validation deadline.

**Findings:** none blocking.

**CLEAR**
