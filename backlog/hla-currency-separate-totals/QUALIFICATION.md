# Currency separation: independent qualification, revision 1

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
Provide a private UTF-8 PostgreSQL DSN, two free loopback ports, and a new absolute
path for `CURRENCY_ACCEPTANCE_UI_REPORT`. Within the same real lanectl namespace
fence, from the candidate root, run:

```sh
CURRENCY_ACCEPTANCE_POSTGRES_DSN='host=/path/to/private/socket dbname=postgres' \
CURRENCY_ACCEPTANCE_HTTP_PORT=18763 CURRENCY_ACCEPTANCE_WEB_PORT=18764 \
CURRENCY_ACCEPTANCE_UI_REPORT=/absolute/path/to/new-ui-result.json \
bash /absolute/path/to/lanectl/backlog/hla-currency-separate-totals/run-dashboard.sh
```

Ensure Node, GNU make and a functioning Playwright Chromium and its runtime
libraries are available in that owned environment. The script starts the real HLA
API over the synthetic PostgreSQL publication and the candidate Next dashboard,
then cleans up owned servers. The helper seeds through the supported loaders and
publisher, clears the warehouse, and drops its random database schema at shutdown.
The spec checks the actual API and the visible dashboard cashflow and utility groups;
it does not intercept requests or change existing snapshots. Its runner parses the
JSON report and requires all three exact tests executed and passed with zero skipped,
unexpected, flaky or reporter errors; zero exit alone is insufficient.

Before and after the run, the independent owner must record the candidate git SHA,
clean tracked/untracked status, and SHA-256 hashes of both runners and all four
acceptance files, and verify they remain identical. Retain those observations,
the complete fenced command output and the Playwright JSON alongside the PG
receipt; reject changes or missing evidence. Re-run for any source or criterion
change. The UI report itself is not a source-binding receipt.

## Historical red controls and provenance

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
