# Guarded built-Next UI smoke preparation

Session-local code only. No deploy, publication, browser, SQL/API runtime, or candidate-positive UI check was performed. Root owns actual future execution, train and independent review. The offline 54 tests use synthetic observations and mocks; they do not qualify a product. Normal M700/max-two gates, existing 55 UI checks, snapshot tolerances and review requirements remain intact.

## How this binds the run

The existing `/projects/dev/lanectl/docs/evidence/2026-11-14-product-contact/api-dev-smoke-preparation/` is reused unchanged. Run its single-attempt `orchestrate.py run` exactly once on the future checked, freshly deployed train; never replay its publisher. Its guards bind receipt, API source/image, fresh volume, audience and network; its SQL verifier establishes API data from independently queried reporting rows. `run.py` calls only the existing guard with `--allow-nonempty`, its read-only snapshot helper, and its `http_verify.py` function, never its publisher. It compares all reporting objects/rows before and after, on failure too. Root must preserve and inspect diagnostics on failure; no unrelated resources are touched.

Successful normal `lanectl deploy run` discards Docker build stdout. Its environment permits PATH, so capture the otherwise-lost build output with the private, process-local shim. This leaves repo and lanectl commands/gates unchanged. `docker_observe.py` invokes the measured real binary with exact args/cwd and relays both streams/exit status; non-build calls are direct exec. Each build records args, cwd, output, exit and before/after conservative tree digest in private files; environment is not logged. Missing/bad logs always refuse. Its digest includes tracked, untracked and ignored names, contents, modes and symlinks (without following), except root `.git` excluded by checked `.dockerignore`; large/special/racing files can refuse. Record written logs are private but build output itself may be sensitive; do not publish without review.

Pre/post checked HEAD, clean Git tree and exact context digest, build args, SHA IDs, observation timestamps within the checked-train/deploy receipt window, successful unexpired checked-train/deploy receipts, image IDs in inspected live containers, compose labels, network and loopback port are checked. The web server's configured API base and its DNS resolution must point solely at the guarded API. This is an **observed controlled-build** linkage, not reproducible-build equivalence or remote cryptographic attestation. Pre/post hashing cannot detect a transient modification reverted during a build; it assumes exclusive trusted source and build ownership, trustworthy real Docker/daemon and protected private logs, no tag substitution or concurrent writers. Base images/npm registry inputs are not independently pinned by this harness. Verify these assumptions and preserve evidence.

## Commands for a future root-owned attempt

Substitute measured paths and actual unique IDs; this preparation does not assert any current train is eligible. Inspect the runner and daemon first. The observer directory must be a new child of this preparation directory:

```sh
python /tmp/hla-ui-dev-smoke-preparation/prepare_shim.py \
  --directory /tmp/hla-ui-dev-smoke-preparation/observer-UNIQUE \
  --docker /ABSOLUTE/MEASURED/REAL/docker \
  --source /projects/dev/_wt/lanes/TRAIN
PATH=/tmp/hla-ui-dev-smoke-preparation/observer-UNIQUE/bin:$PATH \
  /ABSOLUTE/MEASURED/lanectl deploy run TRAIN
```

Capture predeploy fresh-volume absence through the existing harness before the declared deploy. Verify train, checked head, normal deploy and health, exactly two successful shim records, and run the original single-attempt API publisher/HTTP verifier once. Add `web_id` (full 64-character inspected ID) to the original guarded API context JSON. The original guard requires no concurrent operator writes. Selectors must be a separately reviewed JSON mapping to **visible** unique `queue`, `cashflow`, `queueRow`, `title`, `severity`, `link`, `detail`, and each disjoint `components` container; use actual candidate DOM (e.g. attentionRow and main li/dl/tr/data-record-row where applicable). A selector never supplies expected facts. `facts.json` is collected inside the verified API container: original `http_verify.verify()` compares exact Pydantic public rows against parameter-bound SQL and checks all kinds/404/401, then the collector rechecks each payload vs SQL and returns the real feed/records. Browser uses example local auth.

```sh
python /tmp/hla-ui-dev-smoke-preparation/run.py /ABSOLUTE/ACTUAL/CONTEXT.json \
  --observer-dir /tmp/hla-ui-dev-smoke-preparation/observer-UNIQUE \
  --selectors /ABSOLUTE/REVIEWED/SELECTORS.json \
  --browser-image sha256:FULL_LOCAL_UBUNTU_PLAYWRIGHT_IMAGE_ID \
  --docker /ABSOLUTE/MEASURED/REAL/docker
```

The chosen image must be pre-existing, Ubuntu and have Chromium compatible with candidate `node_modules` Playwright 1.59.1; `run.py` inspects its exact local ID and the browser script checks Ubuntu and module version. Docker must resolve to the measured binary used by the original API guard. The orchestrator starts a uniquely named browser container, retains its ID, logs, inspect and daemon inventories in a private `run-*` directory under this preparation directory, then removes only that exact ID. On failure it preserves evidence, including before/after database snapshots. Original guard and source/record checks repeat after browser observation.

Browser follows every visible top-eight link from the real Next page, checks distinct hrefs and navigates directly to each same URL; candidate title ambiguity refuses rather than guesses. The comparator checks stable ranking and labels, all four source kinds, slash identity, same-kind distinct links, required per-source facts, null market reference and multiple rows using one-to-one matching of explicitly disjoint DOM groups on both click and direct-load paths, exact numeric token comparison, no invented anomaly currency and selected history/recommendation phrases. It rejects missing rows and merged or duplicated component facts. It observes Current report and separate cashflow node. Exact text matching and ISO dates may reject valid formatting; fix only through independently verified normalization and negative controls. Component matching checks the needed facts, not every possible extra inferred assertion; manually review no invented savings, recommendations, history or freshness and ensure cashflow month is not attributed to attention. A slash appears in an actual browser click and correct real API/SQL-backed detail, but this harness does not directly trace the server-to-API request bytes. Additional candidate tests must prove exact opaque-key API lookup and status cases.

The actual fixture must contain all four kinds in the first eight, a slash key, multiple source rows, and null market reference; the observer refuses if absent. Never republish or fake data to satisfy it. Existing eight-group fixture cannot prove >8 sorting, unknown severity or 403/503/500: independent frozen actual-Next behavioral acceptance covers those. Browser and user-selected DOM adapter must receive independent review before actual use; no actual candidate-positive execution is claimed.

## Offline controls

```sh
cd /tmp/hla-ui-dev-smoke-preparation
python -m unittest -v test_compare test_binding test_observer test_build_records test_run
/projects/dev/homelab-analytics/.tooling/node-v20.20.1-linux-x64/bin/node test_disjoint.cjs
```

Tests exercise bad source/context/URL/image/backend, absent/extra/failing/malformed build records, stdout/exit/cwd/argument capture and log failure, stale/wrong/missing/duplicated/merged source facts, wrong rank/link/label and a mocked whole-orchestrator wrong-image refusal before browser/publication. They do not test the real browser, SQL, receipt, daemon or image. `binding.py` is an additional pure synthetic oracle, not the real evidence collector; actual runtime collection is in `run.py`, `build_records.py` and the original guard.

The same disjoint predicate was also run with actual Chromium `evaluateAll` in a uniquely owned, network-disabled Ubuntu image container; it rejected nested aliases and accepted sibling rows. The container was removed and its daemon inventory is recorded in `container-expression-inventory.json`. The host Chromium attempt failed because libglib was unavailable; no real candidate UI was exercised.
