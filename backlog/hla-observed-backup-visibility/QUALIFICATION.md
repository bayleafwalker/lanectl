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
passing test are required. The runner independently parses pytest JUnit output and
requires exactly the named published test to execute and pass with no skips, errors
or failures; a zero process exit alone is insufficient. It hashes both criterion
files and itself before execution and refuses evidence if any changes during the
run. Retain the evidence with the candidate review. Re-run
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


## Harness repair and controls

The original revision 2 runner at lanectl commit `6f333c4392aedcac78c3484f844a6f05595d452a`
could mistakenly accept collection-only or skipped runs and recorded hashes only
after execution. Its red baseline above remains historical evidence of a failure,
not a passed receipt. The repaired runner uses receipt format v2 and rejects these
cases. No criterion semantics or original baseline evidence changed.

Run the inexpensive runner controls with a Python environment containing pytest:

```sh
python /absolute/path/to/lanectl/backlog/hla-observed-backup-visibility/test-qualification-runner.py /absolute/path/to/python-with-pytest
```

These use a temporary synthetic candidate and test, not PostgreSQL or product
qualification. The real pytest pass yields a synthetic receipt; real pytest
`--collect-only` and a skipped test both exit nonzero from the runner without a
receipt. A child mutation of a criterion likewise exits nonzero without a receipt.
The control removes its temporary files. A real repaired candidate still requires
the separate PostgreSQL qualification described above.

## Import-order correction

A later HLA target-context lint check found two import-order errors. The only
criterion-file changes here reorder the existing helper import and separate the
existing local import groups; acceptance assertions and the criterion revision are
unchanged. The original revision 1 and 2 source bindings and failures above remain
historical for their original bytes. In particular, the old PostgreSQL evidence is
not rebound to the corrected files and never qualifies a candidate. The required
source-bound PostgreSQL candidate qualification remains mandatory.

With HLA's Ruff 0.15.8 configuration, `ruff check --no-cache --stdin-filename
 tests/<filename> -` passed both corrected files. On historical HLA source
`82dbd9477029d6fda7df67edc617f45a1a4ceb59` in the actual lanectl namespace,
the focused baseline remained 4 expected product failures, 3 controls passing,
no errors/skips: `/tmp/hla-currency-acceptance-2915-source/backup-import-baseline.xml`
and `/tmp/lanectl-resume-20261116/hla-independent/backup-import-baseline.{json,stdout}`.
The published qualification module also imported and collected successfully;
collection is an import check, not a PostgreSQL qualification.

Corrected SHA-256 values: ordinary test
`69bfc9b8c33917cfb46bd7db02dd06ac28502c5df3cb19c06b419785db1b8e7e` and
published test `6123d2ff9bbb37b938ccd4d27aabb68c650885f326c76d7d200c1d8bd73b577f`.
Raw `/tmp` evidence is session-local.

## Canonical base 6c018e78 requalification

The release metadata now names HLA source
`6c018e781186059a6fa6f48d9098c9b2b43a9451`. Revision 2 criteria remain
unchanged from the import correction at lanectl commit `9357`; the earlier 82
results above retain their original source bindings and are not rebound. An
independent archive of the exact new source was prepared at
`/tmp/hla-backup-2914-6c-source` with a separately owned Python environment;
`uv sync --offline --locked --extra dev` ran inside the actual lanectl namespace
using its owned cache. The source's `uv.lock` SHA-256 was
`0f5d60547db05f73fa1f79ec2ec6acc1d08ba3c68d4fc8c8d4f7c90cf7e30142`.

In the same namespace, GNU make `test-target` ran the exact ordinary acceptance
file with pytest caching disabled. JUnit reported **7 executed: 4 expected
product assertion failures, 3 controls passed, 0 errors, 0 skips**. The four
failures are the never-successful target, latest attempt after a success,
observation window/attempt order, and latest successful timestamp/size cases.
JUnit `/tmp/backup-2914-6c-ordinary.xml` has SHA-256
`6a77855adab8a63da457dc8b93b5bc5a60f915a58fcf6a74d7b7ee8cb4ff7986`.
Raw namespace command records and outputs are
`/tmp/lanectl-resume-20261116/hla-independent/backup-2914-6c-{python-setup,ordinary,target-ruff,ruff-version}.{json,stdout,stderr}`.
The exact locked Ruff 0.15.8 passed both acceptance files in the new source's
actual target configuration, with `--no-cache`.

The ordinary and published criterion SHA-256 values remain respectively
`69bfc9b8c33917cfb46bd7db02dd06ac28502c5df3cb19c06b419785db1b8e7e`
and `6123d2ff9bbb37b938ccd4d27aabb68c650885f326c76d7d200c1d8bd73b577f`;
the current published runner SHA-256 is
`205e149e4c7e1a266929ce8b65c15161b3834c2cef133043838e1183878e5a46`.
This is a baseline red control, not a candidate pass. The independent real
PostgreSQL published-path qualification remains mandatory on the exact repaired
candidate. Raw `/tmp` paths are session-local.
