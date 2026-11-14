# Source reader manual review

Candidate: 78bf4f4ca15fe2fbe7086d1018f5533930cb8af4; canonical base: 9cf62cb7271ed0e15e35877ab772709808470bea; worker seed: 0dfdf13e0fb818fcc9e927578fb18d165dd9128f.

## Blockers
None found in this manual review.

## Advisories
None found.

## Watchlist
- Existing reporting_service.py is 1533 lines, above the specialist's 600-line file threshold; it shrank from the 1534-line canonical baseline and remains legacy facade debt. report_routes.py is unchanged at 1257 lines.
- The source lookup and invalid-identity probe are separate store calls; on Postgres they use separate connections. A concurrently replaced publication can be observed across two states. No demonstrated violation of this source packet's static-source acceptance; consider consistency requirements if concurrent refresh becomes a supported guarantee.

## Evidence and coverage
- Reviewed all seven selected specialist concerns manually: overview is the explicitly permitted cross-pack composition point; classification resolves new file ownership; no changed category, unit, nullability, or trust contract; no new backend copy, facade re-export, or new suppression; new source functions stay below size threshold; frozen tests exercise behavior rather than mock the primary unit. Existing file-size debt is recorded above.
- Reviewed four key expressions, full bound SQL, complete matching rows, empty/null identity handling, missing columns, current publication authority and PREFER fallback, exception translation around acquisition/callback, independent list extraction, and no mutation. The two date columns are current NOT NULL schema shapes; packet explicitly excludes manufacturing unsupported expected_date null inputs.
- Product intention pass: stratum-map designates overview as cross-domain composition; data-platform-architecture describes reading pack publications without rederivation and source-run traceability. New code reads current reporting marts and does not change lineage or snapshot authority. Classification calls this APP overview.
- Architecture fallback: `UV_CACHE_DIR=/tmp/hla-review-uv uv run --no-sync python -m pytest -q -p no:cacheprovider tests/test_architecture_contract.py -x --tb=short` passed 101 tests. `make` unavailable in this execution environment; initial uv cache path was read-only, so used /tmp. `git diff --check` passed. No specialist fan-out or external/provider launch occurred.
- No independent full source or real PG suite run here: separate qualification owner runs those. Ordered attention-list parity requires that owner's discriminating check. API, generated contracts, UI, train/dev and canonical CI remain later stages. Review does not declare whole HLA1593 complete.

Clear for source-layer handoff subject to independent qualification and remaining delivery gates; no silent waiver of those gates.
