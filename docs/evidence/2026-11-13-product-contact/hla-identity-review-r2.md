## Verdict: PASS for stage A source

I only read source and diffs. I ran no commands or tests, so every test result below is the worker's report, not my observation. I found no blocking issues. B1 is resolved. The findings below are non-blocking.

## Prior findings

- **B1 (resolved).**
  - **Where:** `TransformationService.refresh_publications` (`packages/pipelines/transformation_service.py:277-289`) now runs the two canonical handlers before attention. It does this when a NULL `charge_id` exists in the summary or upcoming mart and `mart_open_attention_items` is in the requested keys.
  - **Paths covered:** every production caller goes through this method. That includes both promotion paths (`promotion_registry.py:134,151`), so the finance package and overview-only refreshes are both covered. The battery caller never requests attention.
  - **Still fails closed:** the handler guard at `transformation_overview.py:282-285` is unchanged. A direct handler call on legacy rows still raises, and the check still runs before the `DELETE`.
  - **Keys stay visible:** `PublicationRefreshRegistry.refresh` returns the extra keys, and `record_publication_confidence` and `marts_refreshed` both see them. The test asserts `refreshed[:2]`.
  - **Authority:** the repair touches no publication authority code. The `SELECT ... UNION ALL ... LIMIT 1` limits the whole union, so the probe is cheap.
- **N1 (resolved).** The doc now states the hash limit (service name, billing cycle, start date).
- **N2 (resolved).** Date comes from DuckDB `CURRENT_DATE` and from the actual upcoming rows. Item ID uniqueness is asserted at `tests/test_attention_identity.py:105`. The date check is now tautological against the rows, which is acceptable.
- **N5 (partly checked).** The `AGENTS.md` and `CLAUDE.md` diffs are one counter line each. I did not count the migration files to confirm 13.

## New findings

**F1. Published copies are not republished on the repaired path (Medium-Low, behavior to know about).**
- **Where:** `reporting_service.py:190-224` publishes `promotion.publication_keys` plus the overview composition marts. Summary and upcoming appear only in `marts_refreshed`.
- **Trigger:**
  1. Run a finance-only promotion in Postgres mode on a legacy warehouse.
  2. The warehouse summary and upcoming marts are rebuilt, and attention is published with new `upcoming_<charge_id>_<date>` IDs.
  3. The published summary and upcoming relations keep NULL `charge_id` until a subscriptions promotion.
- **Why it's acceptable for stage A:** existing published rows stay authoritative, which is the stated intent. The doc says to republish the finance relations. The API/UI stage must not assume that attention IDs join to published upcoming `charge_id`s.

**F2. "Historical snapshots unchanged" is weakly evidenced (Low-Medium).**
- **Where:** the new test (`test_attention_identity.py:111-146`) checks that a seeded 2025-01 snapshot row survives `refresh_publications`.
- **Gap:** snapshot capture happens in `publish_promotion_reporting` (`reporting_service.py:240`), not in `refresh_publications`, so the test never exercises capture.
- **Trigger:** `mart_subscription_summary` is in `SNAPSHOT_PUBLICATIONS` (`reporting_snapshots.py:71`). A finance-only promotion now lists it in `marts_refreshed`, so capture could write a current-month snapshot. I did not verify whether that overwrites an existing current-month snapshot. Old months are keyed separately and look safe.

**F3. The Postgres falsifier proves the wait-then-add path only (Low).**
- **What it proves:** the production `ALTER ... ADD COLUMN IF NOT EXISTS` blocks behind the held lock, and after rollback it adds the column and preserves old data. Your report says removing the upgrade branch failed at the overlap assertion. That is consistent with the test, since `CREATE TABLE IF NOT EXISTS` evidently doesn't block.
- **What it doesn't prove:** the case where the blocker commits the column while the publisher waits. That is the actual duplicate-column race. Replacing `IF NOT EXISTS` with a plain `ADD COLUMN` would still pass, because the rollback leaves no column to duplicate. Adding a commit variant would cover it.
- **Cleanup is bounded.** The worker connection sets `lock_timeout = 10s`, the waits are 5s, `future.result` has a 10s timeout, and the `finally` always rolls back the blocker so the pool join can't hang.
- **Labelling:** your report says the old thread smoke is labelled. I found no "smoke" or "unforced" text in `tests/test_postgres_reporting_integration.py`, and the repair diff deletes that test. If a label exists, it is elsewhere.

**F4. The new probe raises a raw error on an unmigrated store (Low).**
- **Trigger:** `DuckDBStore.ensure_table` is `CREATE TABLE IF NOT EXISTS` only (`duckdb_store.py:245-248`). If a store has not had migration 0019 applied, the probe on the missing `charge_id` column raises a binder error on any attention refresh.
- **Not a new regression:** the handler guard already had the same exposure. I did not verify where migrations are applied at startup.

## Protected changes

I'm carrying over my earlier disposition. Migration 0019 and the three generated `charge_id` additions are acceptable within the approved identity prerequisite. The repair diff touches neither, and I did not re-read the generated files this pass.

## Not claimed

I did not run verify-fast, the Ubuntu Playwright rendering, the 216 focused tests or the Postgres integration. I also did not assess the APIs, the UI or whole #1593.

**Next step:** F1 and F2 are worth carrying into the API/UI stage. F3's commit variant is cheap to add if you want the `IF NOT EXISTS` choice itself covered.