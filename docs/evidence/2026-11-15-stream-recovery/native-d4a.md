# Verdict: CLEAR

I found no blocker. This is a static source review of the snapshot and `candidate.patch` only. I ran nothing, so none of the reported runtime evidence is something I confirmed. That covers the 76 focused and 1216 full tests, the kernel parent-fsync error, the SHM-hardlink reproduction, and the separate-process WAL runs. The snapshot's `stream_recovery.py` matches the patch: the line anchors and sampled constants agree. I did not compute the `binding.json` file hashes.

## What I checked and what held up

- **Completeness of state.** `_inspect` (`src/lanectl/stream_recovery.py:310-419`) is stricter than `StreamStore.append` (`stream_store.py:101-135`).
  - **Events:** Per scope, revisions are contiguous from 1 and `max == count`. Every event gets the full envelope check, `validate_event`, and a canonical `encode(value) == raw` check. `ContractError` is a `ValueError`, so it is caught.
  - **Batches:** Every batch's result JSON must be canonical and arithmetically exact. The digest is recomputed exactly as the store computes it, `sha256(encode([previous, events]))`. All events in the batch interval must carry the batch principal. The batch intervals must tile `1..head` with no overlap or gap.
  - **Value types:** Blob-typed or non-str values fail the `isinstance` or canonical checks. A stray catalog object, view, trigger or extra table is refused.
- **Snapshot.** The online `backup()` API reads a committed WAL snapshot. The helper then sets DELETE journal mode on the private snapshot only (`:460`), so the artifact payload is standalone. The source is opened with `mode=ro` and `query_only`, and the helper never chmods or alters it.
- **ZIP parsing** (`_bundle`). The checks cover:
  - the central-directory size and offset, and the EOCD arithmetic;
  - exact member names and order, STORED only, no extras or comments;
  - each local header against its central-directory entry;
  - the payload-length sum against the central-directory offset, so there is no hidden or trailing data;
  - CRC verification on read.
- **Manifest parsing.** Duplicate keys, `NaN`, `Infinity`, booleans masquerading as integers, deep nesting (`RecursionError`), unknown keys, and unsorted or duplicate scopes are all refused.
- **Restore sequence.** The helper does these steps in order:
  1. Copy the artifact to an owned file and hash that copy.
  2. Verify the payload hash and length.
  3. Inspect the candidate.
  4. Compute the pre-prep row digest.
  5. Run `_prepare_wal` on the private candidate, which closes the connection.
  6. Confirm there are no sidecars.
  7. Re-inspect with `immutable=1`, which ignores any WAL, so only the main file is read.
  8. Confirm there are no sidecars again.
  9. Compute the post-prep row digest and compare it with the pre-prep one.
  10. Hash the candidate to get `restored_database_sha256`.

  The digest covers every column of `SELECT *`, is length-prefixed with a table separator, and is ordered by key, so it is unambiguous. The coherent principal rewrite, which passes counts and heads, is caught only by this digest. I confirmed the test at `tests/stage9/test_stream_recovery.py:1082` exercises it.
- **Publication.** The sequence is a hard link (so it cannot replace an existing name), then a parent fsync, then `_check_publication`.
  - **Link and fsync order:** `published` is set immediately after the link and before the fsync. Any later failure, including a post-yield `_parent` or `_input` identity check or `cleanup-refused`, therefore reports a real `published` path.
  - **Cleanup:** It removes only entries whose inode matches a retained dup'd fd. It unlinks only the stage name, never the published name.
  - **Tests:** The replace-result and sidecar-race tests assert both of these.
- **SHM guard.** `_source_shm` runs at `:654` and `:443`, before any SQLite open. It uses `lstat` and `_regular` (owner, nlink == 1, mode 0400 or 0600), so symlinks and hardlinks are refused. The `-wal` file is only read, and the test at `:941` shows a read-only WAL alias is not over-refused.
- **CLI.** The bypass at `cli.py:69` happens before `open_log`. All helper exceptions become `RecoveryError`, and the CLI prints structured JSON with `authority_changed:false`. `initialize` is untouched.
- **Docs.** The limits, 2 MiB plus 4 KiB value bound, 300-second deadline, 0600/0700 requirements, `init` umask caveat, and non-claims all match the code.

## Advisories (non-blocking)

1. **Backup can starve under steady writes** (`:455`, `pages=128`).
   - SQLite restarts a stepwise backup when another connection or process writes to the source between steps. A large owner under continuous appends can therefore hit the 300-second deadline and be refused.
   - The refusal is fail-closed and the deadline is documented, but the "while writers continue" claim is only tested with one mid-copy write (`:336`).
   - Minimal fix: use `pages=-1` so one WAL read snapshot is taken in a single step; it does not block WAL writers. Alternatively, document the starvation limit.
2. **Cleanup refusal masks the root cause** (`:160-194`).
   - A `raise` inside the `finally` replaces the original error, for example when SQLite debris is left in the stage.
   - The test at `:575` matches `cleanup-refused`, not the injected `OSError`.
   - Fix: carry the original message in the cleanup error, or record it.
3. **`journal_mode` in the restore receipt is not measured from the file** (`:638`, `:464-472`).
   - It is a constant, backed only by the preparing connection's `PRAGMA` result. A check of header bytes 18 and 19 equal to 2 on the closed main file would make it a measured claim.
4. **Backup validates under the current contract only.** `validate_event` (`:356`) is today's validator, and the catalog check is exact. An owner holding events written under an older contract, or one that has `sqlite_stat1` from `ANALYZE`, would be refused, fail-closed.
5. **Test gaps.** The code handles the cases below, but no test pins them:
   - Owner rows with `NaN`, noncanonical JSON, a tampered batch digest or result, or an event revision gap.
   - Source mode 0400, and a payload whose header claims WAL mode.
   - The backup unsafe-path matrix.
   - `:1082` asserts only `RecoveryError`, not which guard fired.
6. **Undocumented source side effect.** A read-only connection to a source with a live WAL may leave a 0600 `-shm` file beside it, and the doc does not say so.
7. **Unbounded pre-checks.** The `PRAGMA integrity_check` calls (`:301`) on the live source and again on the snapshot are not covered by the 300-second deadline.

## Written product/storage intention pass

The change delivers an explicit, local, read-only-on-source path to snapshot a schema1 owner that includes all committed WAL state, both tables, and the full idempotency records. It restores that snapshot to a new private path as a ready-to-open WAL owner. Replay, conflict, and continuation then behave as on the original. This is owner-source recovery behavior and nothing more.

**Material limits** (all documented in the patch, and I agree with them):
- No hosted backup custody, retention or RPO.
- No persistent-volume recovery, service activation, or authority cutover. `authority_changed:false` and `quiescence:"not-asserted"` are both accurate.
- Hashes detect corruption, not authenticity.
- Inputs need explicit private modes: a 0700 parent and a 0400 or 0600 file. `init` behavior is unchanged.
- Hard bounds apply: 1 GiB, 1M events, 100k batches, 4,096 scopes, and the 300-second deadline.
- A post-link failure can leave a valid, unactivated result. The operator must inspect `published`, and retry refuses replacement.

**Confidence:** about 0.8 for CLEAR. Residual doubt comes from not running anything, from SQLite restart behavior under live writers (advisory 1), and from the unverified runtime evidence.
