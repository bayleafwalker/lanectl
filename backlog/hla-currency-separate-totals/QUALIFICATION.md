# Currency separation: independent qualification, revision 16

Operator decision: preserve original denominations and show separate totals per
currency, without conversion. Work is homelab-analytics#2915; baseline is
`82dbd9477029d6fda7df67edc617f45a1a4ceb59`. This is prospective acceptance,
not a claim that #1590 or any old experiment is complete. The implementer owns
implementation and must address all supported monetary consumers, not only the
representative scenarios here. Existing source normalization, requirements, and
frontend snapshots remain in force. Do not infer a preferred currency, whitelist,
FX rate, or conversion.

All four qualifications below are mandatory on the exact repaired candidate after
the environment prerequisite is qualified. Use the actual lanectl namespace and
credential fence, an owned checkout/environment and private synthetic database,
and retain source-bound records. Never substitute parity or mocks for correctness.
The fixture facts are deliberately out of order: Finance EUR 200 - 30 = 170 and
USD 100 - 20 = 80, same month and counterparty; Utilities EUR 200 / 100 kWh and
USD 100 / 100 kWh, same month and meter. Tests assert values and units independently.
The nonstandard synthetic `ZZZ` code tests the existing three-letter normalizer,
not a currency whitelist. The observed zero bill and usage-only case differ by
currency, bill count and coverage status. The existing summary's compatible numeric
zero is not required to become null. The scalar alone must be unavailable when no
monetary observation exists, and must return 0 USD for a real zero USD bill.

## Required ordinary and PostgreSQL checks

Run the `release.toml` acceptance command, with every test executed, no errors or
skips. The currency grouping assertion has a passing control and intentionally
blended, omitted, swapped, and duplicate currency controls that must fail.

In addition, provision an isolated **UTF-8** disposable PostgreSQL instance and
set `CURRENCY_ACCEPTANCE_POSTGRES_DSN` only for the fenced test process. The owner
must stop and remove it afterward; do not use a production or shared database.
From a clean candidate checkout (with locked dev dependencies installed), run:

```sh
python /absolute/path/to/lanectl/backlog/hla-currency-separate-totals/qualify-published.py /absolute/path/to/new-pg-evidence.json
```

Set `CURRENCY_ACCEPTANCE_MAKE` if GNU make is not on PATH. The runner binds a clean
candidate commit and hashes both criteria and itself before the test, verifies them
afterwards, and independently parses JUnit. Only the exact test executed and passed
with no failures, errors or skips creates a passing receipt. The test publishes an
empty relation, loads the facts through supported loaders, refreshes and publishes,
clears all six DuckDB marts, then checks exact values through strict PUBLISHED HTTP.
It finally repopulates the warehouse, drops the published relation and checks 404;
this last check runs only after all earlier assertions pass. Run after *every*
candidate or criterion change. To independently exercise the runner's receipt
checks with real pytest pass/collect-only/skip and a child file mutation:

```sh
python /absolute/path/to/lanectl/backlog/hla-currency-separate-totals/test-qualification-runner.py /absolute/path/to/python-with-pytest
```

These synthetic runner controls do not qualify a candidate or replace PostgreSQL.

## Required visible dashboard check

Install locked frontend and browser dependencies in the candidate's own checkout;
install all acceptance `files/` artifacts at their corresponding candidate paths.
Provide a private UTF-8 PostgreSQL DSN, two free loopback ports, a new absolute
`CURRENCY_ACCEPTANCE_UI_REPORT` path and a new absolute owner evidence path, both
outside the candidate checkout.
The owner invokes the named-unit driver, not `run-dashboard.sh` directly:

```sh
CURRENCY_ACCEPTANCE_POSTGRES_DSN='host=/path/to/private/socket dbname=postgres' \
CURRENCY_ACCEPTANCE_HTTP_PORT=18763 CURRENCY_ACCEPTANCE_WEB_PORT=18764 \
CURRENCY_ACCEPTANCE_UI_REPORT=/absolute/path/to/new-ui-result.json \
LANECTL_HOME=/absolute/path/to/lanectl \
PYTHONPATH=/absolute/path/to/lanectl/src \
python /absolute/path/to/lanectl/backlog/hla-currency-separate-totals/qualify-dashboard.py \
  --checkout /absolute/path/to/clean/candidate \
  --evidence /absolute/path/to/new-owner-evidence.json
```

Supply the workstation's user runtime directory, Node, a functioning Playwright
Chromium and its runtime libraries, and any needed `PLAYWRIGHT_BROWSERS_PATH` and
`LD_LIBRARY_PATH`. The driver uses the real lanectl `for_train` boundary with a
unique `Sandbox.unit`; its namespace and credential settings are unchanged. It
checks the clean candidate commit and exact acceptance files, hashes the criteria,
runner, process helper and itself before and after the run, and observes the named
unit's effective kill policy and a populated cgroup before releasing it. It waits
for unit completion and verifies the same cgroup is unpopulated or removed. Only
then can it issue a source-bound success receipt. Failure, interruption, missing
proof or cleanup uncertainty is nonpassing. The in-unit UI result is provisional
until that outer receipt exists.

The helper seeds through supported loaders and a real private PostgreSQL publisher,
clears the warehouse, and drops its random database schema at shutdown. The runner
executes mixed and disjoint scenarios sequentially against the actual API and
candidate Next dashboard. It does not intercept requests or change existing
snapshots. It independently parses both Playwright JSON reports and requires all
six exact tests executed and passed with zero skipped, unexpected, flaky or
reporter errors. Raw reports have the requested UI path plus `.mixed.json` and
`.disjoint.json`; the UI result is created only if both phases pass. Retain those
reports, the full driver output and the owner receipt with the PG receipt; re-run
for any source or criterion change.

## Revision 1 historical red controls and provenance

On 2026-11-17 the owned archive of source `82dbd9477029d6fda7df67edc617f45a1a4ceb59`,
with its own `uv sync --frozen --extra dev` environment, was exercised via the actual
lanectl namespace fence. Focused acceptance: **10 product assertion failures, 5
passing controls, zero errors/skips**. JUnit:
`/tmp/hla-currency-acceptance-2915-source/currency-baseline-final.xml`.
Raw fenced output and command:
`/tmp/lanectl-resume-20261116/hla-independent/currency-2915-baseline-final.stdout`
and `currency-2915-baseline-final.json` in that directory. The usage-only scalar
counterexample is HTTP 200 `{"value": 0.0, "unit": ""}`: the existing scalar
contract uses a null value for unavailability, so this numeric value implies money
where only usage was observed. The real zero USD bill control passes with
`{"value": 0.0, "unit": "USD"}`. This does not require changing summary zeros.

UTF-8 PostgreSQL 17.10 with warehouse marts cleared: **1 product assertion
failure, no errors/skips**, because the finance result is a single 250 row without
currency. JUnit `/tmp/hla-currency-acceptance-2915-source/currency-published-baseline-final.xml`;
raw command/output `currency-2915-pg-baseline-final.json` and `.stdout` under
`/tmp/lanectl-resume-20261116/hla-independent/`. Candidate success is not claimed.

The owned locked frontend and Chromium ran against that real published fixture:
**3 assertion failures, no skips or reporter errors**. Cashflow showed €250 instead
of €170 and $80; the utility panel showed €300 instead of €200 and $100. Raw
Playwright JSON `/tmp/hla-currency-acceptance-2915-source/currency-ui-final4.json`;
fenced command/output `currency-2915-dashboard-runner-final4.json` and `.stdout`
under the same `hla-independent` directory. A first Chromium launch failed due to
missing host shared libraries; the verified run supplied available host libraries.
An SQL_ASCII private PG fixture also failed startup on the subscription adapter;
the verified fixture used UTF-8. Neither setup failure is product acceptance.

Baseline SHA-256 bindings: ordinary criterion
`45415c175e49c0b8a89b32226f1c4b8c2b44c57e965b6d2914cba35390deb786`;
PG criterion `55893cd579b2971b67a5b614d50834c4cd0bbda1d45f085704f95e99d19c4eea`;
dashboard fixture `c2fc67e4158cae01265c9a0c6a96ab4743a0cc44bbfc2e8eebd0ec6faf118268`;
UI criterion `31831af34833ac06533bc408143156488da41c4f6bc4aa073dd5798579dc1ae9`;
PG runner `84b44cdbf1ceef759f20ca587f61e30990f69802cde433fe0414ba01093070c7`;
UI runner `2b070450d8694677ca5509e66baec1b205fbc1c65ffe4fda7acc1ff64dfbd26a`.
These raw `/tmp` paths are session-local, not durable. The browser, server and PG
processes were stopped; the owned checkout and caches are disposable scratch.

The UI report parser was separately exercised with synthetic Playwright-format
results: all three passed was accepted; a skipped case and a missing case were each
rejected. This is parser sensitivity evidence only, not a product pass.

Publication and implementation authority remain unresolved. The current native
lane RepoSpec protects `migrations/**` and `requirements/**`; this criterion does
not narrow the outcome or grant that lane authority to change those paths. The
integration owner must resolve the proper execution path after the setup prerequisite
and before publishing the release. Standard interactive source authority does not
itself remove the native lane boundary.


## Revision 2: oracle and lifecycle repair

Revision 1 remains bound to commit `8e2c9fcccb09842209cd91a946f3d3b1ca2a2273`,
its exact hashes and historical evidence above. Revision 2 corrects the amount
oracle to require complete individual visible amount/unit text; Chromium controls
prove `€1700` and `$800` cannot satisfy €170 or $80 and that hidden correct text
cannot satisfy the visible requirement. It adds a disjoint fixture: USD 250
cashflow and EUR 300 utility cost must both remain represented in the household
report and separately visible in the dashboard. The test only checks observed
contributions; it does not impose a zero/null convention on absent fields. The
strict-PUBLISHED PostgreSQL criterion also includes this disjoint report after the
other required assertions and the no-fallback check succeed.

The dashboard helper starts owned backend, Next and Playwright process groups,
catches EXIT, SIGINT and SIGTERM, bounds HTTP connect and response times, and
checks settlement after bounded TERM then KILL waits. Failure to establish helper
cleanup is nonpassing. `process-groups.sh` derives its settlement algorithm from
the reviewed HLA `tools/dev-smoke-process.sh` in setup qualification. Playwright
can launch detached browser groups: the outer named systemd unit and its measured
cgroup are the authoritative settlement boundary, including such descendants.
The driver checks `KillMode=control-group` and `SendSIGKILL=yes` as actually
reported by the named unit; absence of a measurable, initially populated exact
cgroup fails closed. Run both independent real-child controls:

```sh
python /absolute/path/to/lanectl/backlog/hla-currency-separate-totals/test-dashboard-lifecycle.py
LANECTL_HOME=/absolute/path/to/lanectl PYTHONPATH=/absolute/path/to/lanectl/src \
  python /absolute/path/to/lanectl/backlog/hla-currency-separate-totals/test-named-cgroup.py \
  /absolute/path/to/owned/hla-checkout
```

The helper controls exercise INT, TERM, failed startup and TERM-ignoring same-group
children; a simulated nonsettling group must fail closed. The named-unit controls
exercise clean completion, a real detached TERM-ignoring child, an explicit failure,
and INT and TERM cancellation. Each records the exact cgroup and its measured
settlement; no failed or interrupted control creates a success receipt.

During development an earlier lifecycle test timed out and left three owned
synthetic process groups; they were identified, killed and verified absent. A
readiness bug (checking several PIDs in one `kill` call) was repaired. An interim
group-only detached-child test also failed, showing why the named cgroup is required;
raw output is `/tmp/lanectl-resume-20261116/hla-independent/currency-2915-r2-group-final.stdout`.
An interim subreaper experiment was removed after review in favor of the existing
outer cgroup. Its historical raw controls remain at
`/tmp/lanectl-resume-20261116/hla-independent/currency-2915-r2-detached-final.stdout`
and `currency-2915-r2-real-browser-cancel-final.stdout`; they are not current
qualification evidence.

Revision 2 executed against the same historical HLA source and the owned locked
environment through the actual namespace fence. Ordinary acceptance: **11 product
assertion failures, 6 passing controls, zero errors/skips**; JUnit
`/tmp/hla-currency-acceptance-2915-source/currency-r2-baseline.xml`, raw
`/tmp/lanectl-resume-20261116/hla-independent/currency-2915-r2-baseline.{json,stdout}`.
The added disjoint report failure shows finance USD 250 attached to EUR. The
mutation control rejects a missing or relabelled contribution.

PostgreSQL 17.10 UTF-8: **1 expected product assertion failure, zero errors/skips**
at the original mixed finance assertion after clearing warehouse marts; JUnit
`/tmp/hla-currency-acceptance-2915-source/currency-r2-published.xml`, raw
`/tmp/lanectl-resume-20261116/hla-independent/currency-2915-r2-published.{json,stdout}`.
Later disjoint and no-fallback assertions are mandatory on the repaired candidate
and are not claimed as executed in this baseline. The independent PG harness
pass/collect-only/skip/mutation controls were rerun successfully.

Real Chromium and the actual synthetic published backend under the final named
unit: **1 passing visibility oracle control and 5 product assertion failures, no
skipped tests or reporter errors**. This used clean synthetic acceptance commit
`ae52f4db41d4dedcd48da0c4b31d2b2720baa82d` whose parent is the historical HLA
source `82dbd9477029d6fda7df67edc617f45a1a4ceb59`; only the four acceptance files
were added. Raw output is `/tmp/currency-named-baseline-outer-final5.log` and raw
Playwright reports are `/tmp/currency-named-baseline-ui5.json.mixed.json` and
`/tmp/currency-named-baseline-ui5.json.disjoint.json`. The named unit reported its
exact cgroup unpopulated/removed after completion, a nonzero exit and no success
receipt. The JSON parser separately accepted a synthetic all-pass pair and rejected
skipped or missing cases without a success receipt.

The final helper lifecycle controls are in
`/tmp/lanectl-resume-20261116/hla-independent/currency-2915-r2-group-final2.{json,stdout}`:
INT 130, TERM 143, startup failure 1, same-group descendants settled, nonsettling
simulation rejected. Named unit controls and effective policies are in
`/tmp/currency-named-cgroup-controls-final4.log`: clean exit 0, detached-child and
explicit-failure nonzero, INT 130, TERM 143, each exact cgroup settled. The detached
child ignored TERM and systemd escalated; its control is deliberately nonpassing.
These raw paths are session-local, not durable. No repaired candidate pass is claimed.

Revision 2 SHA-256 source bindings: ordinary criterion
`8f75fc2dd84da7d094b9f581acc641171d3e1ba9888208cc79ce4c4df71fc8b7`;
PG criterion `a86188e3b2381e2eded06b5254535f37b2789c6582f934ef5ef87d62f4070b0d`;
dashboard fixture `d3f0dd8effd519cfe0ee297f70e714e7bf05b53938f98b1635a76a100d556591`;
UI criterion `9faa7eab2d20d3106f57f4d79798a913f1a4eb90a6b1c99ba6c5ae729c3006d7`;
PG runner `84b44cdbf1ceef759f20ca587f61e30990f69802cde433fe0414ba01093070c7`;
UI runner `447a4b41b9ab4e573a0952e82ff285239944c657829da30176630def83c3ca8b`;
process helper `c5955acf66c7e1f10c04d9d78f50b578fff42028082b5dcc60fa74a866fcd2c9`;
named owner driver `25da74517d7b0aad30348a5ec9fc8a6aaba039f7bfd4f1abbe1466b876e133f8`;
lifecycle control `bcdb719f7b0aad47e1d369b074d399056a55db7aec4f51a81d634003be794cb7`;
named-unit control `1ad1498ec196cbe3701dea3ecc6c1d6ef084d5c418e3d3df5131b65da1535aca`.


## Revision 3: reject additional relabelled contributions

Revision 2 remains bound to commit `8505466cc609c11ebac26498e5f3d45ca158d97d`,
its exact hashes and historical evidence above. The disjoint reporting oracle now
requires both observed contributions and rejects every additional nonzero cashflow
value outside USD or utility value outside EUR. Null and numeric zero remain valid
for absent fields; no zero-to-null schema change is required. The real-PG test
imports this same oracle. Its controls include the exact counterexample with
USD and EUR rows both containing cashflow 250 and utilities 300, additional
wrong-group values of 1, an unknown `ZZZ` group, and valid zero/null fields.

The actual dashboard check likewise requires the correct visible pairs and rejects
additional visible nonzero wrong-currency values in their respective cashflow and
utility panels. Its Chromium oracle control covers visible €250 and $300 extra
groups, an unknown three-letter code, negative and accounting-style amounts, and
acceptance of zero or hidden extras. These fixture controls do not replace actual
reporting, publication or dashboard checks.

Revision 3 historical baseline, same HLA source `82dbd9477029d6fda7df67edc617f45a1a4ceb59`:
focused warehouse **11 expected product assertion failures and 6 passing controls,
no errors/skips**, JUnit `/tmp/hla-currency-acceptance-2915-source/currency-r3-baseline-final.xml`,
fenced output `/tmp/lanectl-resume-20261116/hla-independent/currency-2915-r3-baseline-final.{json,stdout}`.
Real PostgreSQL **1 expected product failure, no errors/skips**, JUnit
`/tmp/hla-currency-acceptance-2915-source/currency-r3-published-final.xml`, fenced
output `/tmp/lanectl-resume-20261116/hla-independent/currency-2915-r3-published-final.{json,stdout}`.
It fails on the earlier blended finance row; the disjoint published assertions
remain required on a repaired candidate and are not claimed as executed here.

Real Chromium with the final criterion under the named unit: **1 oracle control
pass, 5 product failures, zero skipped tests/reporter errors**. The clean scratch
source commit is `afd68a4a80fd6f3492f3c2da007a67599c32d866` with parent
`ae52f4db41d4dedcd48da0c4b31d2b2720baa82d`, itself parented by the baseline
`82dbd9477029d6fda7df67edc617f45a1a4ceb59`; the revision 3 scratch commit changes
only the ordinary test and Playwright test. Raw owner output is
`/tmp/currency-named-baseline-r3-final2.log`, reports
`/tmp/currency-named-baseline-r3-final2.json.mixed.json` and
`/tmp/currency-named-baseline-r3-final2.json.disjoint.json`. It must not produce a
success receipt. Standalone final browser-oracle control is
`/tmp/lanectl-resume-20261116/hla-independent/currency-2915-r3-browser-control-final2.{json,stdout}`.
The named unit's observed populated and then settled cgroup and effective kill
policy are included in the owner output. No candidate pass is claimed.

Revision 3 hashes: ordinary test
`944076f422a8da0ee2857e3e9e5409a038d66ba86e99806634091c84f4836656`; UI test
`155eebbef03a2c6e3f2791ac18f7de9ebe5af6907692afc501a8ae5d4bdc9548`; published
criterion remains `a86188e3b2381e2eded06b5254535f37b2789c6582f934ef5ef87d62f4070b0d`
and imports the changed ordinary test. Owner and PG runners remain
`25da74517d7b0aad30348a5ec9fc8a6aaba039f7bfd4f1abbe1466b876e133f8` and
`84b44cdbf1ceef759f20ca587f61e30990f69802cde433fe0414ba01093070c7`.

The revision 2 acceptance-only historical source bundle is
`/projects/dev/_artifacts/lanectl-resume-20261117/currency-2915-r2/acceptance-baseline-ae52.bundle`,
SHA-256 `109ae814aa3064bcc254a6b8b9db701f487493f276c9de048579aa661fcf3010`.
`git bundle verify` succeeded; its HEAD is `ae52f4db41d4dedcd48da0c4b31d2b2720baa82d`,
requires parent `82dbd9477029d6fda7df67edc617f45a1a4ceb59`, and the commit diff
contains exactly the four acceptance files. This is host-local selected public
source evidence under `_artifacts`, not durable-authoritative or a full `.git`
archive. All `/tmp` evidence is session-local.

## Import-order correction

A later HLA target-context lint check found import-order errors in the dashboard
fixture and PostgreSQL qualification module. Their existing helper imports were
reordered; acceptance assertions and the criterion revision are unchanged. The
revision 1–3 source bindings, failures, PostgreSQL evidence and UI evidence above
remain historical for their original bytes and are not rebound to these corrected
files. The required PostgreSQL and named-unit UI qualifications must still be run
against the exact candidate and corrected criterion before acceptance.

With HLA's Ruff 0.15.8 configuration, `ruff check --no-cache --stdin-filename
 tests/<filename> -` passed both corrected files and the unchanged ordinary test.
On historical HLA source `82dbd9477029d6fda7df67edc617f45a1a4ceb59` in the
actual lanectl namespace, the focused baseline remained 11 expected product
failures, 6 controls passing, no errors/skips:
`/tmp/hla-currency-acceptance-2915-source/currency-import-baseline.xml` and
`/tmp/lanectl-resume-20261116/hla-independent/currency-import-baseline.{json,stdout}`.
The published and dashboard modules imported and collected successfully;
collection is an import check, not a PostgreSQL or UI qualification.

Corrected SHA-256 values: dashboard fixture
`a4403e3ddde348552d515ddabad3b22ff752d61046b2f1ddf2bb324cec172c91` and
published test `d9fa0f1d6f416d1d59319a0d2b2b3c934e667777d025cdc58dafab36785b238b`.
The ordinary test remains
`944076f422a8da0ee2857e3e9e5409a038d66ba86e99806634091c84f4836656`.
Raw `/tmp` evidence is session-local.


## Revision 4: existing-store upgrade boundary

Revision 3 remains bound to lanectl commit `95c6df74c5ee34f6f83f7da91217f293b6bdd382`
and earlier revision history and evidence above. This revision adds a mandatory
legacy-store qualification; the existing fresh-store, strict published PostgreSQL,
visible UI and lifecycle requirements remain in force.

The seed helper `tests/currency_legacy_fixture.py` requires a clean source checkout
at exact historical HLA commit `82dbd9477029d6fda7df67edc617f45a1a4ceb59`, a new
absolute DuckDB path, a new manifest path outside that checkout and a private UTF-8 PostgreSQL instance.
Under the actual lanectl namespace, invoke it from that historical checkout with
its own installed locked dependencies and `CURRENCY_LEGACY_POSTGRES_DSN` set:

```sh
python /absolute/path/to/lanectl/backlog/hla-currency-separate-totals/files/tests/currency_legacy_fixture.py \
  --warehouse /absolute/path/to/new-legacy.duckdb \
  --manifest /absolute/path/to/new-legacy-manifest.json
```

The owner must provide the normal HLA DuckDB runtime library environment, for
example through the repository's make environment. This creates a random private
PostgreSQL schema named in the manifest; keep that instance and the DuckDB file
unchanged until candidate qualification. Dispose of the owned schema, processes,
and files after qualification. The fixture uses only the source's supported
transaction, bill and usage loaders, refresh and publisher. It records the exact
source commit, fixture/oracle hashes, closed-warehouse hash, all original fact
columns and rows (including IDs, dates, amounts, currencies and run identities),
actual DuckDB/PG publication schemas, all six PG publication row sets and the
old strict-PUBLISHED HTTP response. It has four transaction, two bill and two
usage facts, with EUR170 + USD80 finance and EUR200 + USD100 utility costs.
Both original monthly cashflow tables lack a currency column.

**Candidate qualification is mandatory and not yet executable end-to-end.** The
interactive implementation owner must provide the documented, source-controlled
production upgrade/rebuild and republication entrypoint, including how it selects
the existing DuckDB path and existing PostgreSQL schema, any required configuration
and lifecycle, and how an independent owner obtains equivalent read-only fact
inventory if those legacy relations are replaced. This is an implementation
interface question, not a new currency-policy decision. No command is assumed
here and no migration technique is prescribed. Before acceptance, the independent
owner must bind a clean exact candidate SHA, criterion and fixture hashes, manifest
hash, source schemas and command output; execute that documented candidate workflow
on the *same* populated legacy stores; and verify every original fact and identity
is present once, all original fact values match, no additional facts were invented,
and no conversion or loss occurred. `currency_legacy_oracle.snapshot_legacy_facts`
provides a read-only projection of all original columns when those relations remain
available, allowing added columns; `assert_inventory_unchanged` compares exact
canonical inventories. If the owner chooses versioned replacement, the owner must
identify the supported equivalent read-only projection, and the independent
acceptance author must bind and verify it without weakening the inventory oracle.
An arbitrary supplied JSON, unreviewed extractor, SQL schema patch, dropped/reseeded
store or test-only conversion cannot stand in for the candidate workflow.

The owner must then verify the candidate has replaced the *pre-existing* PG
publications with the correct per-currency API and existing-consumer results; the
expected values and refusal semantics are those of revisions 1–3. After that
republish, clear only disposable warehouse reporting marts and verify strict
PUBLISHED HTTP still returns those correct groups, with no warehouse fallback.
This isolation step is not an upgrade or schema repair and must not alter facts.
Recheck fact inventory after the workflow and isolation step. Existing valid-empty
and unavailable-publication checks still apply. The owner must retain the raw
source-bound reports and may not substitute a fresh store or a parity-only check.
The future end-to-end harness must fail closed for missing interface, fixture,
metadata, exact test execution or evidence; it is not yet a passed receipt.

Historical context only: source `DuckDBStore.open` opens persistent stores and
`ensure_table` does not generally evolve existing columns. Existing HLA also has
`apply_pending_duckdb_migrations` and fact-based refresh patterns, but no chosen
solution is implied; the implementer may use a numbered migration, a versioned
replacement or another supported design. Existing PostgreSQL publishing ordinarily
creates missing tables and does not generally add columns to old ones.

Proof on 2026-11-17: a clean owned exact-82 checkout with its own locked Python
environment seeded private persistent DuckDB and PostgreSQL 17.10 through the
actual namespace; `/tmp/currency-legacy-seed-r4-final-v4.json` records the complete
synthetic inventory and schemas (SHA-256
`e1da7741c210dd4cec9bebe41897c0391365006998bf486ce8908535e35e0be1`). An
independent read-only reopen matched every fact and all six old PG publication
row sets (`/tmp/lanectl-resume-20261116/hla-independent/currency-2915-r4-reopen-v4.{json,stdout}`).
Raw seed output is `currency-2915-r4-seed-v4.{json,stdout}` in that
directory. The disposable PG and DuckDB stores were removed after verification.

A separate reproducible historical-only red control
`tests/currency_legacy_baseline_red.py` reopened another seeded store, verified
the same fact inventory before and after the historical supported refresh and
republish, cleared the disposable warehouse reporting marts, rechecked facts,
and failed on the
strict-PUBLISHED HTTP finance result: one 250 row without currency, rather than
EUR170 and USD80. This is a product assertion failure, not an upgrade pass. Raw
`/tmp/lanectl-resume-20261116/hla-independent/currency-2915-r4-persisted-red-v5.{json,stdout}`;
its separate seed manifest is `/tmp/currency-legacy-seed-r4-final-v5.json` (SHA-256
`284f6c7972f436b2e9462f53bee9fa4c1ed7f32468c152a2c8a769612b6240b6`). The databases and
processes were removed. The baseline red script is never a candidate upgrade path.

The independent inventory oracle controls accepted equal data and rejected removed,
added, relabelled, re-identified, changed-amount, duplicate and missing-column
facts; decimal scale normalization has its own passing control. Combined ordinary
baseline **11 historical product failures, 8 passing controls, no errors/skips**:
`/tmp/hla-currency-acceptance-2915-source/currency-r4-ordinary.xml`, raw
`/tmp/lanectl-resume-20261116/hla-independent/currency-2915-r4-ordinary.{json,stdout}`.
Ruff 0.15.8 passed each new Python file in HLA target context. All `/tmp` evidence
is session-local. No repaired candidate has been qualified.

Revision 4 source SHA-256: legacy seed
`e114a3bed5e8339c9a5705e113d12502bb7ce7c25416910fb8f0a29f03bfb7fa`;
inventory oracle `498adeeb6706721f54de296511fbe58e2e4904919fc031c60bf284a64416c340`;
oracle controls `e14e377b50088ff57884750bb4d3b0f315911aaaf6f10c9609ec5ae7bc0bd4eb`;
historical red control `5c4a19699ac4363c3bedc294a625386a481925a91fbec4759105727db9653b2e`.


## Revision 5: typed facts and pre-seed binding

Revision 4 remains bound to commit `1b99019236c7a71b907a8add9f0ab730a6e24d0d`
and its original evidence above. Revision 5 records the observed type of every
legacy fact column and tags every captured scalar as null, string, integer,
decimal, float, boolean, date, datetime or bytes. Decimal scale alone is
normalized within the decimal type; timezone-aware datetimes normalize to UTC
within the datetime type. A numeric-looking ID remains a string; a
decimal amount is distinct from a string or integer; a date is distinct from
a same-looking string. Unlike reporting's documented absent-field convention,
the original fact inventory does not equate zero with null. A candidate may
add columns, but all original observed types and typed values must be preserved
in the read-only projection. If physical relations are replaced, the independent
author and owner must bind an equivalent typed projection without narrowing this
requirement; the supported candidate workflow remains an open implementation
interface.

The seed captures its own file and oracle hashes before opening or seeding either
store, verifies both again after seeding and before creating the manifest, and
rejects changed or missing files with no manifest. On error it attempts to remove
the owned warehouse and private PostgreSQL schema; cleanup failure is nonpassing.
Two independent real mutation controls
used owned copies under the actual namespace: one changed the seed file and the
other changed the oracle after the warehouse appeared. Both produced nonzero
exit, no manifest, no warehouse and zero remaining private schemas. Raw
`/tmp/lanectl-resume-20261116/hla-independent/currency-2915-r5-mutation-final-currency_legacy_fixture.{json,stdout}`
and `currency-2915-r5-mutation-final-currency_legacy_oracle.{json,stdout}`.

The pure typed oracle controls pass for equivalent decimal scales and unchanged
data, and reject numeric-looking ID type changes, amount string/decimal type
changes, column-type changes, date/string and datetime/string collisions, plus
previous dropped, added, altered and duplicated fact controls. Actual fenced
control JUnit is `/tmp/hla-currency-acceptance-2915-source/currency-r5-oracle-controls-final.xml`;
the combined ordinary baseline is **11 expected historical product failures,
8 passing controls, no errors/skips** in
`/tmp/hla-currency-acceptance-2915-source/currency-r5-ordinary-final.xml`. Raw command
and output use `currency-2915-r5-oracle-controls-final` and `currency-2915-r5-ordinary-final`
under `/tmp/lanectl-resume-20261116/hla-independent/`.

A clean exact-82 historical checkout with its own locked dependencies seeded
the typed fixture in the actual namespace. Read-only reopen matched every typed
fact and all six old PostgreSQL publications. The original supported refresh
and republish retained the fact inventory, then after disposable warehouse mart
clear the strict published HTTP assertion still failed on one 250 row with no
currency. This is historical red evidence, not candidate qualification. Raw
`currency-2915-r5-{seed-final,reopen-final,persisted-red-final}.{json,stdout}` is under the same
`hla-independent` directory. Synthetic manifest `/tmp/currency-legacy-seed-r5-final.json`
has SHA-256 `2b06b04bd0ecf28a229db306ef6eb4961128534032f9b756baf5a7f64fb60868`
and binds source `82dbd9477029d6fda7df67edc617f45a1a4ceb59`, the two pre-seed
file hashes below, actual legacy schemas and the closed-warehouse hash. All
disposable database files, PostgreSQL schemas and processes were removed; these
raw paths are session-local.

Revision 5 source SHA-256: legacy seed
`693c8f0540b55464736b083dd27a32dc43ef0224db16d2c234edd8dd9c90e8fc`;
typed inventory oracle `8db01f61c7abc6c6a20fd3d2df263d6175f0583a24b896bfaa1abfc0a3b1bc33`;
controls `7b4bc2330e0e8a6ee280136625c807ee507f83d74f2540e7f3e489b8eb15ff5d`;
historical red control remains
`5c4a19699ac4363c3bedc294a625386a481925a91fbec4759105727db9653b2e`.
The documented owner-supplied candidate upgrade/rebuild interface and mandatory
end-to-end legacy qualification remain pending; no candidate pass is claimed.


## Revision 6: executable existing-store qualification

Revision 5 and its original evidence remain bound to commit
`904d6cfd0f36a702cdc863630d2743770a6a3371`; no historical evidence is rebound.
This revision supersedes the earlier statement that a candidate interface is still
unknown. The implementation owner proposed `python -m apps.worker.main
upgrade-reporting [--check]`; it is not present on 82 and is not yet qualified.
The supported entrypoint must select the existing DuckDB using
`HOMELAB_ANALYTICS_ANALYTICS_DATABASE_PATH`, and the existing PostgreSQL schema
using `HOMELAB_ANALYTICS_REPORTING_BACKEND=postgres`,
`HOMELAB_ANALYTICS_REPORTING_POSTGRES_DSN` and
`HOMELAB_ANALYTICS_REPORTING_SCHEMA`. `--check` is read-only. Successful upgrade
emits a nonempty completion JSON object only after rebuilding and republishing;
repeating the command is the supported retry. Unknown drift or unsupported views,
grants or dependencies must be refused without changes. No test-only SQL repair
is permitted. This qualification checks a successful repeat, but does not inject
partial cross-store failures or unknown drift; those proposed refusal and recovery
behaviors require additional independent qualification before any claim about them.

Seed fresh owned DuckDB and PostgreSQL stores with `currency_legacy_fixture.py`
using an exact clean 82 checkout and its own dependencies under the actual fence.
It seeds the original mixed January facts and old publications, captures both a
nonempty household snapshot and a valid-empty subscription snapshot, then adds a
February fact. The manifest binds the complete typed fact inventory, physical
schemas, old snapshot bytes, both stores' original publications, seed and oracle
hashes, and the closed warehouse hash. Preserve the generated manifest and do not
reuse a warehouse after a qualification attempt. The database and schema must
already exist; the candidate must perform its own supported upgrade.

Install every `files/` entry in a clean candidate checkout with its own locked
Python and frontend dependencies and Playwright browser. Set `LANECTL_HOME`,
`PYTHONPATH`, and the user bus for the actual namespace; set
`CURRENCY_LEGACY_POSTGRES_DSN` to the private fixture's existing PostgreSQL,
`CURRENCY_LEGACY_PG_DUMP` to its compatible `pg_dump`, and distinct free
`CURRENCY_LEGACY_API_PORT` and `CURRENCY_LEGACY_WEB_PORT`. Set the candidate's
owned browser path and any runtime library paths as needed. Then run:

```sh
python backlog/hla-currency-separate-totals/qualify-legacy.py \
  --checkout /absolute/clean/candidate \
  --warehouse /absolute/private/original.duckdb \
  --manifest /absolute/private/seed-manifest.json \
  --ui-report /absolute/new/ui-report.json \
  --evidence /absolute/new/qualification.json
```

The named namespace unit verifies source, criterion and fixture bindings, requires
one exact executed and passed pytest case with no skips or errors, and emits a
receipt only after exact cgroup settlement. It preserves a JUnit sidecar and the
real browser report. The test compares the entire private PostgreSQL schema/data
and warehouse hash before and after `--check`, checks typed original facts and raw
snapshot rows before and after upgrade and retry, and checks actual rebuilt
DuckDB and republished PostgreSQL currency groups before using reporting code.
After clearing disposable warehouse marts it checks strict PUBLISHED HTTP reads,
including the January household status `legacy_denomination_unavailable` with
empty rows and snapshot metadata, a separate valid-empty old subscription
snapshot, and absent history. A real candidate dashboard must visibly describe
the unavailable January household data; hidden text or a false no-history state
cannot satisfy the UI oracle. No denomination is invented for old snapshots.
Existing usage-only numeric-zero compatibility and the distinct observed zero
bill remain governed by the original criteria.

Real 82 fixture and source-bound negative evidence use clean scratch candidate
`b11c63105a5f0c22bfc1cf093848229f45826dbd` (original 82 production plus
acceptance files). The named owner qualification reached the proposed `--check`
after exact inventory, snapshot, publication and stable PostgreSQL dump checks;
82 returned exit 2 because that subcommand does not exist. One test failed, no
receipt or UI report was emitted, and its exact cgroup settled. Raw log:
`/tmp/currency-r6-owner-missing-v2.log`. The original 82 historical HTTP response
also fails: it returns `snapshot` and a EUR-labelled blended 250 instead of the
unavailable status; raw `currency-2915-r6-history-red-v2.{json,stdout,stderr}`
under `/tmp/lanectl-resume-20261116/hla-independent/`. The two seed manifests
are `/tmp/currency-legacy-r6-missing-v2.json` (SHA-256
`0312a793be3cbcd9068f733677594680fc2eb2772b6dc5d78ece9e8ef3e822d0`) and
`/tmp/currency-legacy-r6-history-v2.json` (SHA-256
`93639718cbac83d40055392da47d648723a8dd7e6c8ceb04af592afd24b516c8`).
The first seed attempt used SQL_ASCII and was refused by the old PostgreSQL store;
the recorded successful fixtures used UTF-8. Databases and processes were removed.

Four focused oracle controls passed under the namespace, rejecting false empty,
no-history, changed/missing/duplicate old snapshots and typed inventory mutation;
raw `currency-2915-r6-oracle-controls-source-final.{json,stdout,stderr}` in the
same directory. A real Chromium control rejects hidden and false-empty messages:
`currency-2915-r6-browser-control.{json,stdout,stderr}`. The named-unit lifecycle
controls accepted a clean exit and rejected a detached TERM-ignoring child,
explicit failure, SIGINT and SIGTERM; each observed the exact cgroup settled:
`/tmp/currency-r6-cgroup-controls.log`. HLA's locked Ruff passed all nine Python
acceptance files in target context. These raw paths are session-local; no candidate
upgrade or full candidate UI has passed.

Revision 6 SHA-256: seed
`6ac674ca84ce6771bf5a5c68b15581384478397448ae68acab0cd159afc0c05d`;
typed oracle `8db01f61c7abc6c6a20fd3d2df263d6175f0583a24b896bfaa1abfc0a3b1bc33`;
history red `0382c33144ded819fdf9efd8d11e6f3eec6e7d33bb616502c377d9b637fd7027`;
upgrade test `1409cad42185625cf50ae6c0e4ac7dd326ceed2e19101703218612a41ef30503`;
UI test `3510486a7ab6425a3eea4a7da28c436feb6c9d9e6d35989b8186ebed081269bd`;
owner driver `4b4ea466646eb837b8484ef84f4892caa6057296abf86ccf4f9805c0c497fa57`;
lifecycle controls `de1c0be680e6840577acb9c6edfa11388652f735d3cb3f1d70a6ed394452787a`.


## Revision 7: verify the first completed upgrade before retry

Revision 6 remains bound to commit `450ef11c8cb9f8dd6b9b17f7efdd82dd9597d3dc`
and its recorded evidence above. Its original test inspected persistent output
only after two commands, so a first run that incorrectly reported completion with
partial output could be repaired by the second and escape detection. Revision 7
requires full verification immediately after the first successful completion,
before the retry can run, and repeats that verification after the retry. Each
inspection checks the typed fact inventory and old snapshot bytes, exact rebuilt
warehouse and republished PostgreSQL currency groups, current and historical
strict PUBLISHED HTTP results, valid-empty versus unavailable history, and the
real past-month dashboard. The warehouse-clear isolation proof remains after the
second verification. The first browser report is retained as the supplied UI
report path plus `.first`; both reports must be newly created and both hashes
appear in the receipt. The named-unit timeout allows for both browser checks.

A focused real pytest control exercises the same sequencing function: a complete
first run produces `run, verify-1, run, verify-2`; a first run returning success
with a partial result fails its verification and the second run never occurs.
Five focused typed, snapshot, history and sequencing controls passed with no
skips or errors in the actual namespace; JUnit is `/tmp/currency-r7-controls.xml`
and raw source-bound runner records are
`/tmp/lanectl-resume-20261116/hla-independent/currency-2915-r7-{controls,ruff}.{json,stdout,stderr}`.
The HLA target-context Ruff check passed. This control is not a candidate upgrade
or proof of an injected cross-store failure; the proposed command still requires
qualification on an actual repaired candidate.

Revision 7 SHA-256: upgrade test
`b8e3113139072bc54ca6442efee1d8594349894e6a3364ab617399600441dddc`;
owner driver
`3de1659a6023ae90c7179841f03a10efe3701a80032f76fe1df173872044cf81`.
The seed, typed oracle, history red and UI criterion retain their revision 6
hashes. Raw `/tmp` paths are session-local.


## Revision 8: realistic partial-first negative control

Revision 7 and its above source-bound controls remain bound to commit
`be47931d2b5991c4704b3715b5d2a48ec4b95cd5`. The sequencing control now uses
the actual currency grouping oracle: a simulated first successful command emits
only EUR 170, while a simulated second would add the missing USD 80. The first
inspection rejects that partial output and the real sequence never runs the
second command; the control then separately demonstrates the hypothetical second
result would pass. A complete result still passes both inspections. No candidate
or product behavior is mocked in the mandatory qualification itself.

Five focused controls passed with no errors or skips in the namespace, and the
new target-context Ruff check passed. JUnit
`/tmp/currency-r7-controls-v2.xml` has SHA-256
`28e438a497c6a41aa7ef3ec7a62b401578f144baf2b3aff44b0c2507d8a48e13`;
raw records use `currency-2915-r7-{controls,ruff}-v2.{json,stdout,stderr}` under
`/tmp/lanectl-resume-20261116/hla-independent/`. The revised upgrade test has
SHA-256 `80471783f058fef014041cd66bbc2bf173f1575fc39ffbaa3674474f4a4bf0bf`;
the revision 7 driver and remaining source bindings are unchanged. These paths
are session-local and no candidate pass is claimed.


## Revision 9: empty legacy schema is not valid-empty

Revision 8 and its original evidence remain bound to commit
`e8e6372ac4be94a46aebf51e51f37ad566cc5d13`. A legacy monthly cashflow
relation can have no rows and still lack the currency column required for this
outcome. A row-only check cannot establish its shape. On the actual reporting and
HTTP path, an empty old-shaped monthly relation must be refused with a handled,
explanatory schema/currency/upgrade error; an empty current-shaped relation is
HTTP 200 with empty rows. The focused examples cover this one relation, not every
monetary guard. The new ordinary checks use real private DuckDB WAREHOUSE reads.
The mandatory published qualification runs both cases against a private real
PostgreSQL schema with strict PUBLISHED reads, while its separate DuckDB warehouse
contains a USD row; it must not fall back. Fixture DDL constructs only synthetic
old and current shapes and does not repair a product store. Existing first-run,
retry, typed fact and legacy history requirements remain unchanged.

The canonical published runner hashes the new helper before and after execution,
in addition to its prior criterion and harness bindings. Its five synthetic
runner controls passed: actual pass, collection-only refusal, skip refusal,
existing criterion mutation refusal, and new helper mutation refusal. Raw
`currency-2915-r9-runner-controls-final.{json,stdout,stderr}` and target-context
Ruff output `currency-2915-r9-ruff-final.{json,stdout,stderr}` are under
`/tmp/lanectl-resume-20261116/hla-independent/`.

A historical 82 archive, with owned dependencies, was tested through the real
API in the actual lanectl namespace with private DuckDB and PostgreSQL 17.10.
Both current-shaped empty controls passed; both old-shaped empty relations
incorrectly returned HTTP 200 with `rows=[]` and failed the new assertions.
JUnit `/tmp/currency-r9-empty-baseline-v3.xml` records **2 expected product
failures, 2 passing controls, 0 errors and 0 skips**, SHA-256
`4189daebda38552e054bd58097a3f26d9168f2d41c417235b727e03a43f247e4`.
Raw `currency-2915-r9-empty-baseline-v3.{json,stdout,stderr}` is in the same
namespace evidence directory. The relevant historical API, reporting,
transformation, storage and finance-model source files were individually compared
byte-for-byte with git source `82dbd9477029d6fda7df67edc617f45a1a4ceb59`.
The owned PostgreSQL schemas, server and temporary directory were removed. This
is baseline red evidence, not candidate qualification.

Revision 9 SHA-256: empty-shape acceptance
`d94cf907cbe04d7405ef2ceb20df3d6a0a89fb7f697fd894faff80615f5aa76b`;
published test
`826a37c7d71c1f0f859c2b8cf5f52c83580a77e58bf9c31da10eb40b382d0136`;
published runner
`226492237cd96366867499f07e62dedd2e1064a9517d9c090c100ca0c2ef854a`;
runner controls
`93fdeb781b2a6e5e2f1ccbc26ed2b1c69585ccce482a2d4d92a8aec067be97e0`.
Raw `/tmp` paths are session-local. Earlier published, UI and legacy evidence
remains historical for the original criterion and harness bytes; do not rebind it.


## Revision 10: independent maintenance failure scenarios

Revision 9 remains bound to commit `0772039d03ab38ea4d5ae5dd47dc434aed0e8908`
and all earlier evidence remains bound to its original bytes. The owner-side
legacy qualifier now requires three **additional**, independently seeded 82
warehouse/manifest pairs in the same private PostgreSQL instance. Set absolute
paths before running the existing `qualify-legacy.py` command:

```sh
export CURRENCY_LEGACY_DRIFT_WAREHOUSE=/absolute/private/drift.duckdb
export CURRENCY_LEGACY_DRIFT_MANIFEST=/absolute/private/drift.json
export CURRENCY_LEGACY_DEPENDENCY_WAREHOUSE=/absolute/private/dependency.duckdb
export CURRENCY_LEGACY_DEPENDENCY_MANIFEST=/absolute/private/dependency.json
export CURRENCY_LEGACY_OUTAGE_WAREHOUSE=/absolute/private/outage.duckdb
export CURRENCY_LEGACY_OUTAGE_MANIFEST=/absolute/private/outage.json
```

Seed every pair with the same supported 82 fixture process as the main pair,
using distinct PostgreSQL schemas and files. The driver binds all four seed
manifests, fixture and oracle hashes, original warehouse hashes, candidate
source and acceptance bytes; the main successful full upgrade and retry, with
first-run inspection, remains a prerequisite before any adversarial result can
contribute to a receipt. Missing commands or commands that always refuse cannot
qualify. Every scenario starts from the recorded original facts, snapshots and
published inventory; the three added stores are independent of one another.

* **Unknown drift:** add a synthetic unknown column to the private legacy PG
  monthly relation. Both `--check` and upgrade must return nonzero, with the
  injected store and DuckDB unchanged; typed facts and raw snapshots remain.
* **Dependent view and grant:** add a real dependent PG view and a PUBLIC SELECT
  grant to the disposable schema. `--check` must leave both stores unchanged.
  Upgrade may refuse unchanged or succeed, but on success the original view
  definition and grant must survive, as must original typed facts and snapshots;
  exact January Finance EUR 170 and USD 80 must appear in both stores.
* **PostgreSQL unavailable:** select a nonexistent private socket, requiring
  nonzero `--check` without store changes and nonzero upgrade without a false
  completion. Preserve typed facts and old snapshots even if an implementation
  performed partial work; restore connectivity and require the same supported
  command to complete and produce the same exact Finance groups in both stores.
  This proves an unavailable-store failure and safe retry; it does not inject or
  claim a specific mid-transaction failure point or atomic cross-store behavior.

A failed command may not report a success status or `success: true` JSON.
Refusal checks compare the whole warehouse file and stable PG dump, including
private schema, rows and permissions. Other legacy outputs and UI remain covered
by the prerequisite full upgrade; the three adversarial scenarios explicitly
check their listed outcomes, not all possible drift, grants or failures. SQL here
only introduces owned synthetic defects/dependencies; it never repairs candidate
schemas. No implementation order is prescribed.

Four focused namespace controls passed, including rejection of success-as-refusal,
warehouse or PG mutation during refusal, changed view/lost grant, false-success
JSON, and partial-first upgrade ordering; JUnit
`/tmp/currency-r10-oracle-controls-v2.xml` SHA-256
`fccb4a4083ee412c984a3b1e012cbe0550bfbb19d747e4c5a1a383cbc13b54ed`.
The actual target Ruff check passed. The named-unit lifecycle controls retained
clean, detached-child, failure, SIGINT and SIGTERM behavior, with cgroups settled:
`/tmp/currency-r10-cgroup-controls.log`. The four-fixture driver ran against a
clean acceptance-only scratch commit `76bace4fece927656be7636293c0bb122556093d`
with original 82 product source: the missing public command failed `--check`,
produced no receipt, and the exact unit settled. Raw
`/tmp/currency-r10v2-missing.log`, seed records
`/tmp/lanectl-resume-20261116/hla-independent/currency-2915-r10v2-seed-{main,drift,dependency,outage}.{json,stdout,stderr}`.
The four owned PG schemas and warehouses were removed with the private server.
This negative control stops before the new adversarial scenarios; those scenarios
have not yet been run end-to-end on a candidate. No candidate pass is claimed.

Revision 10 SHA-256: adversarial helper
`955761b31af8e828d85cbba5b8fadf4c713c1255e7de09fdc7d0ebae191bdc02`;
legacy test `9ef8c320cc3c4cf6bedca1687490cff59a8e3e6d00662089b0d1e3d05f313475`;
legacy driver `dd9358b342920c7af0fe8ec4ca82313054907986fccb8733c51e42c296c87f72`.
All `/tmp` paths are session-local.


## Revision 11: accept the explicit US-dollar symbol

Revision 10 remains bound to commit `8c8914aacc5beb6905fb8013917d8b90254916bd`.
An independent qualification on production parent
`e83d058c8e8a579d181f79fc7acf5a7d8e2b7a78` and acceptance-only child
`92c8b0367794ed0b4d07c3fa72c800968b936755` passed the ordinary and published
checks but the dashboard matcher rejected the visibly rendered `US$250.00`.
The prior positive matcher accepted `$` and `USD`, but accidentally omitted
`US$`, even though the same test's wrong-unit oracle already recognizes that
symbol as USD. This is an acceptance-oracle defect; the historical Q result is
not a candidate pass and is not rebound to this revision. The retained evidence
is host-persistent and semi-ephemeral at
`/projects/dev/_artifacts/lanectl-resume-20261117/currency-2915-q-qualification/manifest.json`;
the legacy qualification was not run after the dashboard failure.

The exact visible amount matcher now also accepts `US$` as USD. A real Chromium
control in the lanectl namespace first failed on visible `US$80.00` with the old
matcher, then passed after the correction. It also verifies `US$800.00` cannot
satisfy 80 and a hidden `US$80.00` cannot satisfy the visible requirement;
the earlier euro, dollar, hidden, opacity and wrong-currency controls remain.
Raw `currency-2915-r11-browser-{red,green}.{json,stdout,stderr}` is under
`/tmp/lanectl-resume-20261116/hla-independent/` and is session-local. Revised UI
criterion SHA-256 is
`09782ecfe20232262edd4c704840ed66a718928bd7c3a5323893eec7e3ebcff1`.
A fresh clean acceptance-only child and all required candidate qualifications
must be run with the new criterion; no earlier receipt is rebound.


## Revision 12: monetary consumer and usage evidence

Revision 11 remains bound to `de2a8aaad720c10640eea621e6b32829bb1fc51e`;
all original UI, publication and legacy evidence retains its own source and
criterion bindings. The ordinary acceptance now independently exercises real
loaders, reporting and public APIs for these additional behaviors:

* A tariff scenario must refuse or make its monetary scalar unavailable when
  finance and utility denominations differ, utility data contains multiple
  denominations, or usage exists without a monetary bill. It must preserve
  correct same-EUR arithmetic and distinguish a real observed zero EUR bill.
  For a valid all-USD scenario, its existing monetary assumption unit must say
  USD rather than the generic word `currency`.
* The electricity contract decision must not sum mixed EUR and USD components
  into a qualified scalar. An all-USD assessment and its baseline must not
  label estimated USD amounts as EUR/year; the all-EUR calculation remains a
  control. These checks use the existing public subject and assessment interface,
  not a prescribed replacement field layout or conversion policy.
* A EUR bill of 100 for 100 kWh plus 100 kWh from a separate unbilled meter
  must not assign that unbilled usage to the EUR group and halve its unit price.
  The single billed-meter case remains an independent passing control.

On frozen product P2 `e4303e4b61e73596a5b567af907f11504ba5aaff` (same runtime
product bytes as P1), an acceptance-only clean scratch child
`92617bd71666aaf6a170d991ca090fb65909575f` contains exactly the new consumer
criterion and its existing shared fixture. In the actual lanectl namespace it
produced **7 expected product assertion failures and 4 passing controls, with
0 errors and 0 skips**. The failures are the three unrepresentable tariff
cases, all-USD tariff unit, mixed-components decision, all-USD decision unit,
and the billed/unbilled denominator. Controls cover same-EUR and genuine zero
tariff results, the same-EUR decision, the billed-only denominator, and the
false-zero/dropped-group oracle. The control test count is four because the
same-EUR and zero tariff checks share one case. Target-context Ruff passed.

Selected host-persistent, semi-ephemeral evidence and an acceptance-only Git
bundle are in
`/projects/dev/_artifacts/lanectl-resume-20261117/currency-2915-r12-consumer-red/`.
The JUnit SHA-256 is
`187522fdfe34ae228e1bfb9ad79dcfa495b391bc99f6c72e4d8a25dca5e73470`;
the new consumer criterion SHA-256 is
`3d79ad018e813c3af7b554c28c1b6899bfc6cfef90b1f81b77bf7d6ef6f424c5`.
This P2 red run is not a candidate qualification and is not rebound to later
product source. The independent P1 legacy diagnostic separately stopped after a
successful read-only check when the revision 10 harness rejected multiple JSON
stdout records before the command's completion record; no legacy receipt was
emitted, and the remaining scenarios were not run. Its host-persistent evidence is
`/projects/dev/_artifacts/lanectl-resume-20261117/currency-2915-q1-legacy-diagnostic/`.


## Revision 13: household projection cannot hide a blend

Revision 12 remains bound to commit `e129c32f4a5fd326575bac6256ce4c180b896bee`
and its original P2 red evidence above. Its tariff helper could accept null
utility scalars while returning a deficit estimate or a persisted blended
household projection. Revision 13 checks the entire observable consequence.
The operation may refuse. If it returns HTTP 200, an incompatible household
projection must be explicitly unavailable, with an unknown deficit; if a scenario
identifier is returned, its public comparison and cashflow endpoints must refuse
or explicitly indicate unavailability without exposing scenario or variance
projection rows. A separately representable USD utility scalar may remain
available with the correct USD assumption unit and arithmetic. Mixed-utility or
usage-only money still cannot be represented as an observed scalar. The checks
use the existing interfaces and do not require a particular status-field name or
conversion, nor do they prescribe implementation strategy.

The oracle control rejects the exact counterexample: null utility fields plus a
persisted-blend scenario and a non-null deficit. It also rejects a null deficit
with exposed persisted rows and rejects empty rows presented without an explicit
unavailability signal. Positive controls accept operation refusal and a valid
USD utility amount with explicitly unavailable household projection; existing
single-currency and observed-zero controls remain.

Against the same frozen P2 product source, the separate acceptance-only scratch
child `8062cdd51ebf56734f7cf03182b614f6fbf9ee5d` differs from P2 only in the
new consumer criterion and its shared acceptance fixture. The actual namespace
run produced **7 expected product assertion failures, 4 passing controls, 0
errors and 0 skips**, and target-context Ruff passed. An earlier revision-13
interim run reached the public cashflow endpoint and observed persisted mixed
projection rows; the final stricter check may reject the earlier unmarked 200
response first. Both results are retained independently. Host-persistent,
semi-ephemeral evidence, including a source bundle, is under
`/projects/dev/_artifacts/lanectl-resume-20261117/currency-2915-r13-consumer-red/`.
Final JUnit SHA-256 is
`45dc2fd112e0208e24d0f2e049a8c1e8ba3f7858271af2c9b8de144ff29c8ea8`;
interim JUnit is
`a5ad654421a8e1089a216c085ebd7982850027faa2859763b8ea9f68be640ee3`;
consumer criterion SHA-256 is
`9d0986cda66648101e842f017b8cac08a87a802f66b7dd641455e42d68aae963`.
These are historical red controls, not a repaired candidate pass.


## Revision 14: discover projections after refused operations

Revision 13 remains bound to commit `8f16bc6abc0501e771fa5cf696a9c5732e6552c6`
and its original red/control evidence is unchanged. A refused tariff operation
can still leave a discoverable scenario with a blended projection; likewise a
200 response without a returned ID must not hide such a scenario. Before each
incompatible POST the oracle reads the supported scenario catalogue with
`include_archived=true`; after the POST it reads it again, identifies every new
scenario and includes any returned ID, regardless of response status. It fetches
both public comparison and cashflow endpoints for all such IDs before checking
whether each refuses or explicitly reports unavailable with no projected rows.
A metadata-only refused scenario is allowed. This does not require rollback,
particular storage strategy, or changes to unrelated existing scenarios.

The real catalogue must return a parseable list of distinct nonempty IDs; errors,
missing IDs, malformed responses and duplicate IDs cannot silently mean no new
scenarios. The positive control parses an existing ID and permits newly created
metadata with unavailable projection endpoints. Negative controls prove that a
422 followed by a discoverable blended projection is rejected and that both
endpoints are called, and prove the same for a 200 response with no returned ID.
They retain revision 13's null-header, persisted-row, ambiguous-empty and valid
USD utility-only controls.

Against frozen P2 product `e4303e4b61e73596a5b567af907f11504ba5aaff`, the clean
acceptance-only scratch child `6f07fdf1de03b60591a0495a1a2a7942def43d3c` differs
from P2 only in the consumer criterion and its shared test fixture. The actual
lanectl namespace run produced **7 expected product assertion failures and 4
passing controls, 0 errors and 0 skips**; target-context Ruff passed. The separate
source-bound oracle control also passed. Selected host-persistent,
semi-ephemeral evidence and verified acceptance-only bundle are under
`/projects/dev/_artifacts/lanectl-resume-20261117/currency-2915-r14-consumer-red/`.
The final JUnit SHA-256 is
`758def5665debce4862a978e6d286537815b29251f579fc9cfbae078adc84f3f`;
the new criterion SHA-256 is
`a17ea4155f1063c465363dcd55016d0245a3c5c0a20364959b8062ceee50acda`.
These are historical red/control results, not a repaired candidate pass.

## Revision 15: denomination labels and legacy column preservation

Historical revisions and evidence retain their source bindings. The scenario
oracle reads the explicit currency and price-baseline year for compatibility
fields whose names end in `_eur`. A historical field name does not establish
the unit. The live scenario detail tests create a scenario through the supported
API, open its actual page in a browser, and require coherent currency context
for EUR and USD. The history selector requires exactly one matching entry and
still checks the historical unavailability and original snapshot metadata.

Seed one additional isolated pair at the historical source using the same
procedure as revision 10. Set these variables as well as the revision 10
variables before running the owner-side legacy qualifier:

```sh
export CURRENCY_LEGACY_WAREHOUSE_DRIFT_WAREHOUSE=/absolute/private/warehouse-drift.duckdb
export CURRENCY_LEGACY_WAREHOUSE_DRIFT_MANIFEST=/absolute/private/warehouse-drift.json
```

The DuckDB fixture places a populated synthetic column on the rebuilt household
overview. Check must leave both stores unchanged. A targeted refusal must be
read-only in both check and upgrade, or a completed upgrade must preserve the
column's observed values and yield exact outputs from the original facts.
The PostgreSQL fixture probes populated columns on monthly cashflow and
household overview separately. Each requires a relation-specific schema refusal
in both modes and an unchanged warehouse and full publication dump, including
the sentinel. Each PostgreSQL injection is removed from the owned fixture only
after its refusal and preservation are proved. Typed facts and original snapshot
bytes remain checked. The controls reject generic subprocess failure, the wrong
relation, false completion, and dropped, changed or duplicate sentinel values.
These independent cases exercise both ALTER and republish-only maintenance
paths. Per-relation coverage requires separate checks.

The full criterion also requires every rebuilt mart as the sole drift target
in its own exact-82 fixture. Set `CURRENCY_LEGACY_DRIFT_MATRIX` to an absolute
directory outside the candidate checkout. From the clean historical source
and using the same private PostgreSQL instance as the other seeds, enumerate
`MARTS` from `files/tests/currency_drift_inventory.py`. For each relation, run
the established seeder with the additional `--drift-relation <relation>`
argument and these output names:

```sh
python "$criteria/currency_legacy_fixture.py" --drift-relation "$relation" \
  --warehouse "$CURRENCY_LEGACY_DRIFT_MATRIX/$relation.duckdb" \
  --manifest "$CURRENCY_LEGACY_DRIFT_MATRIX/$relation.json"
```

The historical reporting service publishes the target relation in each fixture.
If it contains no rows, the qualified probe introduces one disposable derived
row with typed values and a populated sentinel. It leaves source facts and
historical snapshots intact. Each PostgreSQL refusal is checked before the
probe removes its own injection and proves the pre-injection publication state.
A separate DuckDB injection on the same isolated pair then proves unchanged
refusal or a complete upgrade preserving the sentinel. The owner-side driver
binds each original warehouse hash, manifest and PostgreSQL schema. The
matrix runs after the normal first successful upgrade and idempotent retry.

The visible projection oracle requires an explicit unambiguous unit and every
monetary cell from the corresponding live cashflow rows. Its browser controls
reject hidden units, a bare dollar with no explicit denomination, conflicting
currencies, other dollar symbols, and missing or incorrect values. The annual
energy decision independently checks current cost, alternative cost and
difference by field in both the assessment and the baseline.

After a PostgreSQL outage failure, inspect the original typed facts, snapshot
rows, disconnected publication schema and unrelated warehouse relations before
restoring access. The only eligible partial warehouse changes are the declared
derived marts, snapshot-format maintenance and the schema migration marker.
The observed original snapshot rows and all unrelated values, including a
foreign sentinel, must survive. The ordering control rejects a retry that
could conceal an earlier damaging change. Drift diagnostics bind the affected
relation by identifier in the actual refusal message.


## Revision 16: presentation styling and publication preflight

The projection oracle maps headers using the authored heading text. A visible
control applies the production uppercase heading style and still requires the
same denomination and amounts. The immutable revision 15 UI result remains
bound to that revision and captured the heading-style mismatch.

The strict PUBLISHED checks create a real PostgreSQL schema with the target
relation absent, then query the public report with the DuckDB target independently
legacy-shaped and absent. Both return the explicit published-relation
unavailability diagnostic. Current-shaped empty publications remain valid.

Set `CURRENCY_LEGACY_PG_HAZARDS` to a new absolute directory. Seed five additional
exact-82 pairs with the same fixture command used for the matrix, always passing
`--drift-relation mart_household_overview`. Name their files `<hazard>.duckdb` and
`<hazard>.json` for `trigger`, `row-security`, `foreign-key`, `ownership` and
`numeric-typmod`. Use the same private PostgreSQL instance and a fixture login
that can create a disposable role. The qualification creates a real BEFORE
TRUNCATE trigger, enabled RLS policy, populated inbound foreign key, non-owner
role with DML access, or populated incompatible numeric typmod, in separate
fixtures. It requires targeted refusal with unchanged warehouse and full PG
schema/data/ACL dump for check and upgrade, and rechecks the original typed facts
and raw history. The owner-control fixture uses a non-superuser effective role
so the owner mismatch is real and confined to the target mart.


Use four distinct free loopback ports. Set `CURRENCY_LEGACY_API_PORT` and
`CURRENCY_LEGACY_WEB_PORT` for first upgrade verification, and
`CURRENCY_LEGACY_RETRY_API_PORT` and `CURRENCY_LEGACY_RETRY_WEB_PORT` for the retry.
The owner driver prechecks and records all four. Each browser run still checks
its listeners and stops its server and process group before advancing. Seed the
main warehouse with a filename such as `legacy-MAIN.duckdb`, which keeps its
catalog name distinct from the DuckDB `main` schema.

The ordinary consumer tests also load genuine one-to-many and many-to-many
billing observations and check the original invoice totals, observed quantity,
distinct counts and unit costs through the public summary. The income-change
test checks the public refusal and absence of persisted scenario rows for a
cross-currency delta, then uses the same fixture to verify an exact same-unit
income projection and explicit USD assumption.
