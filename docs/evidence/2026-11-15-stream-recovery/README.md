# Explicit stream backup and restore qualification

Owner-source commit `7cf63655b57ac8de757a533aa45a7074cae27065` adds explicit
`lanectl stream backup DATABASE ARTIFACT` and
`lanectl stream restore ARTIFACT DESTINATION`. The source hashes and exact test
population are in [source-qualification.json](source-qualification.json).
The later workflow-only commit is `0155dc0498077e7ab2301a5137acdfe7d7f59637`.
The integrating owner subsequently prepared version `0.2.15` with a metadata-only
commit recorded in the source manifest. That changes the two distribution
version fields; it does not rebind prior source reviews or claim a published
release, built wheel or installed tool. Replacement CI will test that version.

The final local population passed **1,217 tests**, with zero failures, errors or
skips; all **77 recovery tests** passed. Unmodified stdout is retained in
[full.log](full.log) and [focused.log](focused.log). Ruff check, Ruff format check
and whitespace checks passed. The real systemd user manager and mount
namespaces were available for the full suite; an earlier sandbox/bus failure is
attributed separately in [prior-runs.json](prior-runs.json).

[runtime.json](runtime.json) records actual independent writer, backup CLI,
restore CLI and reopen processes on disposable synthetic fixtures. It proves
committed uncheckpointed WAL state, both tables and every stored row survive;
old batches replay their acknowledged result, changed content conflicts, a new
batch advances revision, and scopes remain separate. The restored main file
reopens in WAL mode before and after append. A main-file-only live copy omits
committed rows and was falsified. A real kernel `fsync(/dev/null)` error injected
at parent sync produced no successful receipt, retained the published result,
left a usable artifact and refused replacement on retry. No authority state or
owned staging candidate remained. The public-safe [harness](runtime-harness.py)
is included for reproduction; it creates its own fixtures and requires a fresh
proof output path.

[closed-wal-falsifier.json](closed-wal-falsifier.json) and the normalized
[red test log](closed-wal-red.log) preserve the final measured defect against
the preceding `d4aeb3d` source. A wrapper prepared WAL normally, then changed
the closed private candidate back to DELETE. Counts, heads and logical rows
still matched, so the old restore published a database with header versions
`1,1` while claiming WAL. The final source requires the SQLite magic and both
closed main-file header versions `2,2` before hashing, fsync and exclusive
publication. The new regression proves the actual rewrite and targeted
refusal, with no destination publication or source/artifact loss. Earlier
source passes are never rebound to the final source.

[reviews.json](reviews.json) binds two independent native static source reviews
and the integrating agent's report of first-party Sage review. The full
`d4aeb3d` review was CLEAR before the concrete WAL falsifier; its seven
nonblocking advisories remain visible in [native-d4a.md](native-d4a.md). The
bounded final `7cf6365` recheck is [CLEAR](native-7cf.md), with no permission
denials or blocking findings. Neither native review ran the tests or reproduced
the runtime evidence. The final first-party source review also reported CLEAR.

[ci-preflight.json](ci-preflight.json) records actual local read-only, writable,
inaccessible-path, deadline and stop checks, plus a guard-removed negative
control. The first public Ubuntu CI run is linked there: setup and all real
isolation preflight checks passed, but the full suite **failed two existing
stage1 tests; 1,215 passed** in 163.33 seconds. The selected
[failure summary](ci-ubuntu-first.log) is retained without runner identifiers or
operational setup logs. This is a recorded failed full run, not an Ubuntu pass.

[dash-portability.json](dash-portability.json) proves its fixture cause using
actual dash and bash bytes. Existing fake-provider `echo` commands expanded
JSON's literal backslash-newline escapes under dash, yielding invalid JSON.
A disposable seam changed only the fake executable shebang to actual dash:
the same two assertions failed ([red log](dash-targeted-red.log)). Three JSON
emissions now use portable `printf` in the separate, fixture-only commit
`32a4a503d7ec74ad885f37005581d128fffb0ea6`. All original assertions remain;
the same 12 tests pass under [actual dash](dash-targeted-green.log) and
the [host shell](host-shell-targeted.log). Production owner source remains
exactly `7cf6365`; the full population remains 1,217. The replacement complete
Ubuntu CI result is pending.

This is local owner-source qualification. It establishes no hosted backup
custody, persistent-volume recovery, retention, RPO, service activation,
installation or authority cutover. Hashes detect corruption, not authenticity.
Inputs require private owned parent/file permissions; ordinary `stream init`
under umask `0022` needs explicit owner preparation before backup. The existing
schema, import/configure marker and authority selection are unchanged. A
post-publication sync failure can leave a valid, unactivated result; retry
refuses replacement. The 300-second deadline bounds the online copy phase,
not every integrity/catalog precheck; sustained writes can exhaust it.

Only selected public-safe evidence is included. Temporary fixture paths were
normalized in runtime metadata and local paths/object addresses removed from
the red logs; trailing whitespace was removed from those derived logs. The original hashes are retained. Native envelopes were reduced
to review text and allowlisted source/execution fields. Raw JUnit hostname
fields, provider/session identifiers, credentials and host operational payloads
are excluded. `SHA256SUMS` covers these selected files. Original scratch proofs
are session-local; this directory becomes cross-host-replicated when the
integrating owner publishes the reviewed Git commit.
