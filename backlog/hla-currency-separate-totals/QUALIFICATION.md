# Currency separation: independent qualification, revision 2

Operator decision: preserve original denominations and show separate totals per
currency, without conversion. Work is homelab-analytics#2915; baseline is
`82dbd9477029d6fda7df67edc617f45a1a4ceb59`. This is prospective acceptance,
not a claim that #1590 or any old experiment is complete. The implementer owns
implementation and must address all supported monetary consumers, not only the
representative scenarios here. Existing source normalization, requirements, and
frontend snapshots remain in force. Do not infer a preferred currency, whitelist,
FX rate, or conversion.

All three qualifications below are mandatory on the exact repaired candidate after
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
install the four `files/` artifacts at their corresponding candidate paths.
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
