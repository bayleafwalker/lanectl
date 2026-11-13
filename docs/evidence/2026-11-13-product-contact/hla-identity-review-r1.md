## Verdict: HOLD on stage A source, with one narrow fix or an explicit acceptance needed

I read this from the patch and source only. I ran nothing, so every test result below is the worker's report, not mine. The protected migration and generated-contract changes are reviewable within the approved identity prerequisite. Details are at the end.

## Blocking

**B1. Upgraded warehouses can fail unrelated finance and overview refreshes (Medium-High, operational).**
- **Where:** the new guard at `packages/domains/overview/pipelines/transformation_overview.py:282-285` raises when any `mart_upcoming_fixed_costs_30d` row has a NULL `charge_id`.
- **Why it matters:** `mart_open_attention_items` is also in the finance package's `refresh_publication_keys` (`packages/pipelines/household_packages.py:96-113`). That list has no subscription summary or upcoming marts ahead of it. Only the subscriptions package orders summary, then upcoming, then attention (lines 143-149).
- **Trigger:**
  1. Upgrade a populated DuckDB warehouse with migration 0019.
  2. Before subscriptions are rebuilt, run a finance-only refresh, for example after a transaction ingest.
  3. The refresh reaches the attention step with legacy NULL rows and raises `ValueError`.
- **Unverified:** I did not read how the refresh runner propagates that error. It could fail the ingest or only the step.
- **What is correct:** the check runs before the `DELETE`, so no data is lost, and failing closed matches the "no silent fallback" requirement.
- **Resolution, either of:**
  - Make the finance and overview refresh paths rebuild subscription summary and upcoming first. This is the cleaner option.
  - Have the coordinator explicitly accept that the operator must rebuild subscriptions before any finance refresh, with the doc at `data-platform-architecture.md:595` updated to say so. Either way, add a test that drives the finance-package refresh against a populated legacy mart.

## Non-blocking findings

**N1. Known scope limit: `charge_id` cannot separate "distinct same-name/date/amount charges" (Medium, document it).**
- **What `charge_id` hashes:** `subscription_charge_id` (`subscription_models.py:158-165`) hashes only `service_name|billing_cycle|start_date` and is the fact table's PRIMARY KEY (line 66).
- **What collides:** two charges that differ only in contract, provider, amount or currency share an ID.
- **Not checked:** I did not check how `insert_rows` treats that collision.
- **Why it matters:** the brief's "distinct same-name/date/amount charges" case can't be expressed with this ID. The approved choice was the existing ID, so this is a scope limit, not a defect.
- **Request:** state the limit in the doc addition. The new tests cover only charges with different start dates.

**N2. Date-sensitive assertions can fail in some timezones (Low-Medium, test-only).**
- **Where:** `tests/test_attention_identity.py:68` compares `upcoming_{id}_{date.today()}` against rows computed from DuckDB `CURRENT_DATE`. The seed dates at lines 409-410 also come from Python's date.
- **Trigger:** if the Python and DuckDB dates differ for part of the day, the expected date shifts. I traced the case where Python's date is a day behind (a host west of UTC with DuckDB on UTC). Expected becomes `today+7`, so the test fails for several hours daily. Whether DuckDB uses UTC or the host timezone here depends on the build's ICU support, which I did not check.
- **Cases that hold up:** a Python date ahead of DuckDB still matches. The renewal dates are fixed `valid_to` values, so they are unaffected. The two-component weekly seeding and the 10/20-day renewal windows are otherwise sound.
- **Fix:** derive the expected date from `SELECT CURRENT_DATE` in the same store, or from the returned upcoming rows.

**N3. Postgres `ensure_table` (`packages/storage/postgres_reporting.py:42-71`) is sound but has rough edges.**
- **What holds up:**
  - Evolution is additive only, adding a nullable `TEXT` `charge_id`.
  - Identifiers are validated and quoted, and the schema is qualified.
  - An incompatible type raises and the transaction rolls back.
  - `replace_rows` truncates and inserts in one transaction, so a failed insert leaves the old rows.
- **Hard-coded special case:** it is limited to two table names and `charge_id`, with `TEXT` hard-wired rather than derived from the column type. This is acceptable given "don't build a framework", but the next additive column will need the same edit.
- **Locking:** `ADD COLUMN IF NOT EXISTS` takes an `ACCESS EXCLUSIVE` lock on every republish, even when the column exists. `replace_rows`'s `TRUNCATE` already takes that lock, so the extra cost is small. Checking `information_schema` first would avoid it.
- **Weak concurrency test:** `tests/test_postgres_reporting_integration.py:551-558` swallows `DuplicateColumn` and retries. Two pool threads don't force an overlap, so the race may never happen and the test passes either way. Treat it as smoke coverage, not proof of concurrency safety.
- **Test size:** the Postgres test is about 70 lines covering many scenarios. That is under the 80-line threshold but poor for diagnosing a failure. Consider splitting it into upgrade, schema scoping, incompatible type and rollback.

**N4. Attention dedupe is by exact projected row, not by `item_id` (Low).**
- **Where:** `SELECT DISTINCT` at `transformation_overview.py:303` and `:313`.
- **Exact duplicates collapse:** this meets the "only exact equivalent rows" requirement.
- **Residual risk:** two rows with the same `item_id` but a different title or severity would both survive. Today `score` is a function of `reason` and provider is per contract, so I found no real trigger.
- **Suggestion:** add an `item_id` uniqueness assertion to the new test.
- **Preserved:** anomaly IDs are unchanged and `upcoming_payments` has no `DISTINCT`. Both are correct given the primary-key-unique `charge_id`.

**N5. Documentation and housekeeping (Low).**
- **Key change:** `data-platform-architecture.md:589-591` states the upcoming and renewal ID change and tells consumers to discard old IDs. That meets the key-compatibility request and is kept separate from the additive-column text. My search for persisted consumers of attention IDs was truncated at 40 files, so I can't confirm that nothing stores old IDs, such as dismissals or MQTT state.
- **CLAUDE.md:** the migration-state table still lists DuckDB 0018 and a count of 12. It should show 0019 and 13.
- **Column order:** upgraded DuckDB tables get `charge_id` appended last, while fresh tables have it first. This is harmless because the code uses named columns.
- **Publication contract version:** the `semantic-ownership` prompt asks about contract changes without a version bump. The change here is an additive nullable column. I found no publication-contract version field to bump, but did not search exhaustively.

## Specialist prompts

Seven prompts were applicable.
- **No findings:** `suppression-drift` (no new suppressions in the diff), `pack-boundary`, `stratum-coherence`, `repetition-vs-abstraction` and `god-class-file-size` (I measured no file sizes). Overview SQL reading finance and utilities marts predates this diff.
- **`test-quality`:** advisory notes N2 and N3 only. I found no empty or trivially true assertions.
- **`semantic-ownership`:** N5 only.

## Checks against the requested review points

- **Exact identity:** the upcoming attention ID uses `charge_id` plus expected date. The renewal ID now includes the renewal date, so contracts with several components and distinct dates keep separate items (the test asserts two).
- **Old data:** populated legacy marts keep NULL `charge_id` and are never backfilled. The attention refresh rejects them (see B1). Old snapshots project NULL with `snapshot.projected` (`test_reporting_publication_snapshots.py:587-605`).
- **Published authority and layers:** the Postgres test asserts that existing published rows win over the warehouse and stay identity-less. I found no warehouse fallback or layer-split violation in the diff.
- **Protected changes:** migration 0019 is the minimal additive `ADD COLUMN IF NOT EXISTS` on two tables that exist since migration 0001. I found no dependent views or indexes. The generated files contain exactly the three `charge_id` additions, which the manifest change implies. I could not re-run generation, so I rely on the worker's contract-export check.

## Out of scope and not claimed

I did not evaluate verify-fast, the web-ui-test screenshot baseline, or whole #1593.

**Next step:** once B1 is fixed or explicitly accepted, I would move this to PASS. N1 and N2 are worth fixing in the same pass, and the rest are optional.