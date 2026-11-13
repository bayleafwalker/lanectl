# Review-synthesis: HLA a5 timeout artifact (source scope only)

Source `/tmp/hla-a5-timeout-source`, HEAD `6831e8b872cd…`, base `9cf62cb7…`. This is a read-only source review. It is not a candidate approval, and it does not reclassify the native a5 outcome (failed 124 at 2700.1s, rejected; a6 is live).

## Verdict: HOLD

I found no behavioral defect in the required API contract. HOLD comes from two structural blockers raised by the repo's own specialist rules (B1, B2), both fixable without changing behavior. I read the specialists' size and classification claims as file reads and greps; I did not run line counts myself. If the operator waives them, the remaining findings are advisory.

## Findings

**B1 — blocker (stratum-coherence, sonnet). New file in a Transitional package has no classification.**
- File: `packages/pipelines/reporting_attention_records.py:1`
- Evidence:
  - `docs/architecture/stratum-map.md:39` says new files in `packages/pipelines/` "must carry an explicit classification before they are merged."
  - `pipeline-ambiguity-classification.md` has no row for the file, and no docs file mentions it.
  - The module mixes finance and utilities relation names and key SQL with generic exceptions and a query builder.
  - The sibling files `reporting_service.py` and `reporting_snapshots.py` are also unclassified, so the precedent is lax.
- Recommendation: add a classification row. Optionally move the per-domain `AttentionSourceRecord` definitions into the owning domain packs.

**B2 — blocker (god-class-file-size, haiku). Files that were already oversized grew past the 2x rule.**
- Files: `packages/pipelines/reporting_service.py` and `apps/api/routes/report_routes.py`.
- Evidence (specialist counts, base inferred from the patch hunks):
  - `reporting_service.py` is about 1456 lines, +68 net, against 576 for the next-largest file in its package.
  - `ReportingService` now has 75 methods.
  - `report_routes.py` is about 1209 lines, +55 net, against 539 for the next-largest in its package.
  - `register_report_routes` runs about 638 lines.
- Recommendation: move the reader (`get_attention_record`, `_attention_source_read`, `_attention_record_source`) next to `reporting_attention_records.py`. Move the route registration into its own route module.

**A1 — advisory. `table_exists` runs outside DB-error conversion.**
- File: `packages/pipelines/reporting_service.py:885-887`
- Trigger: the publication store is unreachable. `PostgresReportingStore.table_exists` (`packages/storage/postgres_reporting.py:34`) opens a connection, so a `psycopg` error escapes as an unconverted 500, not the 503 the contract promises for an unavailable source.
- Relevance is concrete but narrow. The sibling `_fetch_published_or_fallback` behaves the same way, so this is not a regression against existing endpoints.
- Recommendation: move the `table_exists` call inside the `(duckdb.Error, psycopg.Error)` conversion.

**A2 — advisory. The item-id formula has two owners.**
- File: `packages/pipelines/reporting_attention_records.py:34,42,50,58`
- Evidence: `packages/domains/overview/pipelines/transformation_overview.py:294,304,314,331` builds the same four expressions inline. I checked them and they match exactly today. Nothing enforces that they stay equal.
- Raised by both semantic-ownership and repetition-vs-abstraction.
- Recommendation: share one definition, or add a generator-to-lookup round-trip test.

**A3 — advisory (semantic-ownership). The lookup does not share the generator's filters.**
- File: `packages/pipelines/reporting_attention_records.py:78`
- Evidence: the generator applies `days_until_renewal <= 30`, `expected_date <= today+7d` and `DISTINCT`. The lookup reads the whole source mart, so it can resolve ids that are not open attention items.
- This fits the "source-publication record" requirement and looks intentional. Please state it as the intended contract.

**A4 — advisory (repetition-vs-abstraction). `_attention_record_source` copies `_fetch_published_or_fallback`'s mode decision tree.**
- File: `packages/pipelines/reporting_service.py:870`
- Recommendation: extract a shared resolver, or comment why the copy is deliberate.

**A5 — advisory (stratum-coherence). `reporting_service.py` now imports `duckdb` and `psycopg` and chooses `?` or `%s` placeholders itself.**
- File: `packages/pipelines/reporting_service.py:892`
- There is no landing shortcut; reads stay on mart relations.
- Recommendation: push the driver-specific parts behind the store abstraction.

**A6 — advisory (test-quality). Several committed tests are weak or slow-only.**
- File: `tests/test_attention_record_api.py`
  - **Slow-only coverage (`:1112`, `:1143`):** empty-identity and missing-column tests are slow Postgres tests, deselected by `-m 'not slow'`.
  - **Loose status assertions (`:1171`):** the forged empty-identity assertion accepts 400, 404, 422 or 503, so a probe regression to 404 would pass.
  - **Single-case NULL, empty and `None` coverage (`:636`, `:507`):** it covers only `upcoming` `charge_id` rather than all four kinds.
  - **PUBLISHED-only 503 tests (`:614`):** no WAREHOUSE-mode 503 test.
  - **Stand-in store (`:89`):** `DuckPublicationStore` replaces the Postgres store in the portable path.
- The supplied runtime probes do cover the four empty-component cases and the literal-`None` controls on real Postgres. That evidence is not the committed default suite.

**W1 — watchlist.** The key and the unkeyed probe are two non-atomic reads. A concurrent replace can only produce 503, not a wrong 404.

**W2 — watchlist.** Key concatenation is ambiguous with underscores (for example `review_a_b_c`). This is inherent to the existing opaque format, and the generator already collapses such ids with `DISTINCT`.

**W3 — watchlist.** `CAST(date AS VARCHAR)` depends on a Postgres `DateStyle` that renders ISO dates. The supplied Postgres probes passed with the default.

**W4 — watchlist.** The generated-TypeScript test (`test_attention_record_api.py:745`) is a substring check.

**W5 — watchlist.** Many pre-existing files over 600 LOC remain, unchanged by this diff. The file-size specialist enumerated them, mostly under `packages/storage`, `packages/domains` and `packages/application`.

## Requirements I verified from source
- **Routes and ids:** four `GET /reports/<segment>/records/{item_id:path}` routes use the whole opaque id, including an encoded slash. They return `{item_id, rows}` with the existing public row models.
- **Query binding:** the exact key is bound in SQL (`attention_record_query`) before any limit or Python selection. NULL components never match because `||` yields NULL and explicit guards exclude them.
- **Literal `None`:** the guards test SQL NULL and `''` only, so a nonempty literal `None` stays valid and distinct from NULL. I found no new format or empty-display restrictions.
- **Strict PUBLISHED:** a missing relation raises Unavailable (503) rather than reading the warehouse.
- **Unavailable vs unknown:** an empty result with any unkeyed row gives 503, otherwise 404.
- **Missing column or driver error:** converted to 503.
- **Safe failure detail:** route errors use fixed strings and `from None`.
- **Permissions:** `auth_policies.py:393-402` derives the permission from the first path segment. Each source route gets its own `reports.read.publication.<segment>` permission, distinct from `attention-items`. The committed tests `test_attention_record_api.py:834` and `:856` assert attention-only gets 403.
- **Generated contracts:** the generated OpenAPI and TypeScript hunks match the four routes (read from the patch, not regenerated).
- **Scope:** the patch changes no grant, auth-policy, migration, frontend or dependency files, and has no suppressions (the suppression-drift specialist returned `[]`).
- **Busy handling:** `apps/api/warehouse_access.py:48` maps `WarehouseBusyError` to a safe 503 with a different body shape. This is canonical handling by inspection only, with no busy runtime proof.

## Assumptions and missing verification
- All gate and runtime results are supplied evidence, not run by me: acceptance, base, diff, Ruff, both real-Postgres probe suites, and `tests/test_architecture_contract.py` (101 passed).
- Full `verify-fast`, train, dev and CI are not complete.
- `expected_date=None` is not admitted by the public row model or the fresh store. No HTTP probe for it was run, and I make no claim about it.
- I have no runtime proof for the busy path or for `table_exists` failure.
- Specialist LOC counts are theirs, with the base inferred from the hunk headers.
- I did not independently confirm that the `schema_version` and migration constraints are untouched beyond the file list in the patch.

## Product-intention pass
- **Core operating picture:** the picture wants explainability ("Explainability beats novelty", §3.3) and attention surfaces that are "trustworthy enough to act on". Resolving an attention id to its exact source rows without guessing, fabricating or substituting warehouse data fits that intent.
- **Kotona brief:** Stage B1 calls for a lineage drill on the brief's attention section. This endpoint is a prerequisite for that drill, which matches the stated scope. It does not cover the UI, deployment or the rest of Work 1593.
- **Four kinds:** the outcome keeps all four kinds together, with no per-type destinations or historical fallback.

## Specialist and model coverage
- Native fan-out was available and used.
- Haiku scans:
  - `pack-boundary`: `[]`.
  - `suppression-drift`: `[]`.
  - `god-class-file-size`: two blockers (B2) and watchlist entries.
  - `test-quality`: advisories and watchlist entries (A6, W4).
- Sonnet synthesis:
  - `stratum-coherence`: one blocker (B1) and two non-blocking findings (A5, one watchlist note).
  - `semantic-ownership`: advisories and a watchlist note (A2, A3).
  - `repetition-vs-abstraction`: advisories (A2, A4).
- I wrote the exception-path, permission, product-intention and consolidation work myself. I confirmed the stratum and key-formula findings against source before relying on them.

## Result
**HOLD** for this source scope, pending B1 and B2, or an explicit operator waiver of those two repo rules. This is a source-review result only. It does not approve the failed native a5 attempt, and it does not change the timeout outcome (124 at 2700.1s, rejected). Full `verify-fast`, train, dev and CI are still outstanding.
