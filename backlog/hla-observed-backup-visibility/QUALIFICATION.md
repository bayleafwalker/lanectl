# Mandatory independent published-path qualification (revision 2)

Revision 1's original four tests, baseline source binding and failures remain in
`/tmp/lanectl-resume-20261116/backup-base-host.xml` and
`/tmp/lanectl-resume-20261116/backup-baseline-proof.json` (host-local, not durable).
The baseline was HLA `82dbd9477029d6fda7df67edc617f45a1a4ceb59`, against
lanectl criterion base `555d2fe`. Revision 2 adds assertions and retains those
original tests unchanged. The old evidence is not candidate evidence.

The owner must run **both** the ordinary `release.toml` acceptance command and
this independent qualification against the exact repaired candidate commit before
accepting it. The candidate checkout must be clean, with project dependencies
installed and `make test-target` working. If `make` is not on PATH, set
`BACKUP_ACCEPTANCE_MAKE` to the GNU make executable. Supply a private, disposable PostgreSQL
instance via `BACKUP_ACCEPTANCE_POSTGRES_DSN`; this test creates and drops its own
random schema, and must not use a production or shared database. There is no skip,
warehouse fallback, or substitute mock for this requirement. The owner provisions
and tears down that instance. Never put its DSN into the evidence file.

From the candidate repository root, with `BACKUP_ACCEPTANCE_POSTGRES_DSN` set:

```sh
python /absolute/path/to/lanectl/backlog/hla-observed-backup-visibility/qualify-published.py /absolute/path/to/new-evidence.json
```

A zero exit and an evidence record with the exact candidate commit, clean checkout,
criterion and harness SHA-256 hashes, PostgreSQL server version, zero exit and a
passing test are required. Retain the evidence with the candidate review. Re-run
for any candidate or criterion change; do not rebind old evidence. The harness
fails if the checkout changes during its run. The test uses the supported loader,
refresh and publisher, clears the warehouse mart, and verifies rows over strict
PUBLISHED HTTP. It also checks empty publication and missing-publication 404 with
warehouse data present. It checks the row inventory, no duplicates, window and
latest-attempt values, and the successful source started_at and size. It does not
assert configured targets with no facts or invent a never-successful size.

Revision 2 baseline: focused suite 4 expected product failures, 3 controls passing,
no errors/skips; original two failures are preserved. The additional control feeds
synthetic correct and mutated responses through the added assertions; last-inserted
status, all-ever count, nonzero older-only count, completed_at, and wrong success
size each produce an assertion failure. Independently on PostgreSQL 17.10, the
published qualification failed because only `retrying` was returned after warehouse
clear (expected three observed targets). This baseline is a red control, never a
qualification of a future candidate. The temporary private PostgreSQL instance was
stopped and removed. Current XML results are host-local at
`/tmp/backup-rev2-final.xml` and `/tmp/backup-published-rev2.xml`.
The source-bound baseline harness record is `/tmp/backup-rev2-source-bound.json`
(host-local): candidate `82dbd9477029d6fda7df67edc617f45a1a4ceb59`, PostgreSQL
version `170010`, exit 2; test SHA-256 values are
`ce89f269cec3868b862c4bb427a4eed292d00681106e13bd74d22015c15d8ff7`
(ordinary) and `86ae8600e69237892cf1c4e5a18836de04637dddfd2b79f81bbbb314cdb21f92`
(published). The script SHA-256 is
`0cb7c20bfeb35b78eed35f8c50c801d7527679c4e6e7c35e0056fcc20645418e`.
