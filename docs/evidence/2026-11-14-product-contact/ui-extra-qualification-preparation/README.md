# Extra UI qualification preparation

Status: prepared only. No UI candidate, deployed runtime, production database, or UI implementation was inspected or changed by these probes. A passing result is not claimed until a real native candidate has completed successfully and all recorded gates pass.

Use only a clean disposable `/tmp` checkout of the actual full 40-character candidate SHA, with the exact frozen `tests/test_attention_current_ui_acceptance.py` SHA-256 `57c9e9eef945a90d133a7a0f2b29194b1d9df7cd6a0007c52a50672b1fc02bf5`. The runner refuses other roots, mismatched SHA, dirty checkout and unexpected frozen bytes. In an authorized host shell, for example:

```bash
cd /tmp/EXACT-DISPOSABLE-CANDIDATE
source tools/project-env.sh
python /tmp/hla-ui-extra-qualification/run_candidate.py \
  --checkout "$PWD" --sha FULL_40_CHARACTER_CANDIDATE_SHA \
  --output /tmp/NEW-UNUSED-UI-EXTRA-RESULT
```

The runner executes two candidate-local tests through `uv run --no-sync` and rejects skips or incomplete JUnit. The first uses the frozen test's disposable Next/browser lab and a controlled, synthetic authorized transport to require all four kinds, separate component rows and correctly associated visible label/value pairs. It covers both non-null and null market reference. It is a transport test, not proof of real API authorization or publication.

The second builds a disposable synthetic PostgreSQL publication and serves the actual candidate API/reader. It intentionally updates its synthetic `mart_contract_review_candidates.market_reference` to `17.3456`, checks the real API result, then asks the actual Next page/browser for the record and checks the labeled value at full precision. This is a fixture mutation: it proves an isolated current API read and UI transport only; it does not prove that the publisher originally produced that value or that a deployed environment does. A market reference need not carry its own currency label. Required current/expected prices must have their source currency in the price or associated row.

The semantic browser observer supports description lists, tables, ARIA labeling, visible adjacent label/value spans and labeled paragraphs. Matching requires disjoint DOM subtrees for separate records. Its label vocabulary is deliberately bounded; if a valid accessible layout uses another expression, inspect the actual DOM and extend this external observer rather than declaring the candidate incorrect solely for unsupported markup. It detects explicit fabricated component identity/name/type/label fields and headings such as `Component Tax` or `Component 1`, while permitting provided price/date/provider facts and generic structural headings; this does not prove the absence of every conceivable invented phrase.

`offline.log` records 29 passing pure-oracle controls, including wrong, missing and rounded market values; null-as-zero/omission; swapped labels in all four kinds; fabricated component labels; nested aliases; a separate row-level currency; and an unchanged market reference without its own currency. `browser-controls.log` records matched Ubuntu Playwright controls over isolated DOM snippets for description lists, spans and paragraphs, and rejects wrong/missing reference, swapped labels, fabricated components and nested one-row aliases. These snippets test the observer; they are not a UI prototype or runtime success evidence.

`run_candidate.py` and `ownership.py` write a parent-readable, fsynced ownership ledger in a newly created mode-0700 output directory. Scratch runtime observers mark only their unique Docker containers with a per-run label and record exact full CID/name plus the spawned Next PID, process group and `/proc` birth identity. On timeout or SIGINT/SIGTERM, the supervisor records the original failure, interrupts only its own process group, attempts only identity-verified owned cleanup and verifies daemon inventory; it records cleanup failures separately and retains partial stdout/stderr. If a child or identity cannot be verified, it does not claim cleanup or attempt a broad sweep. `lifecycle-controls.log` shows forced timeout and cancellation through the uv wrapper with a real disposable labeled container and process, plus refusal controls for a mismatched birth, daemon inventory failure, wrong container label and malformed ledger.

The frozen acceptance remains unchanged. These files are session-local under `/tmp`. No literal NaN is sent as JSON; literal JavaScript NaN remains untested until a genuine candidate transform boundary is identified and independently exercised.
