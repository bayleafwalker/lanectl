# Revised dispatch plan: homelab-analytics#1593 (record-specific attention destinations)

**Verdict: HOLD on one contract gap, for upcoming payments only.** Three of the four item types can get a real per-record destination using identifiers and permission rules that already exist. Upcoming payments (`upcoming_cost`) have no record identity in any published data or read API. Everything except that one type is ready to dispatch as scoped below.

This was a read-only pass against `b41e4c9` using Read, Grep and Glob only. No tests ran.

## Findings

**1. Attention item IDs are promised to be stable but aren't unique for two of the four types.**
- The data contract describes `item_id` as a "Stable synthetic identifier for the attention item" (`packages/domains/overview/manifest.py:87-88`). The query that builds the list is `transformation_overview.py:288-338`.
- The underlying contract-price table has one row per price component, not one per contract (`transformation_contract_prices.py:103-125`). The repo's own fixture has a contract with two components (`tests/fixtures/contract_prices_valid.csv:2-3`, Helen Spot energy + base_fee).
- **Contract renewals:** the ID is just `'renewal_' || contract_id` (`:310`). The renewal watchlist has one row per component (`transformation_utilities.py:683-698`), so a contract with two components that renews within 30 days produces two items with the same ID. If the components have different end dates, those two items also differ in severity and detail.
- **Contract reviews:** the ID is `'review_' || contract_id || '_' || reason` (`:300`), and reviews are also flagged per component (`transformation_utilities.py:612-645`). If several components get the same reason, the items are duplicates. Severity depends only on the reason (`:633-641`), so removing exact duplicates loses nothing.
- **Anomalies are fine.** `transaction_id` is the primary key of `fact_transaction_current` (`migrations/duckdb/0001_initial_schema.sql:187`), and each transaction gets at most one anomaly type (`transformation_transactions.py:612-620`).
- No test checks uniqueness. `tests/test_transformation_overview.py:232` only checks that each ID is non-empty.
- Nothing stores attention item IDs. The decision-ledger code only mentions "attention" for operator minutes. The morning brief builds its own IDs from them in memory (`test_morning_brief.py:380`). So the renewal ID format can safely change.

**2. Upcoming payments have no record identity in published data. This is the HOLD.**
- The ID is `'upcoming_' || contract_name || '_' || expected_date` (`transformation_overview.py:326-327`).
- The upcoming-payments table has no key column at all (`0001_initial_schema.sql:361-369`). It is built from the subscription summary, whose rows are individual charges (`transformation_subscriptions.py:102-125`).
- The real identity is the charge: `charge_id = hash(service_name, billing_cycle, start_date)`, the primary key in the charge facts table (`:72-76`). Neither `charge_id` nor `start_date` is published in the summary or the upcoming-payments table.
- Two active charges for the same subscription with the same billing day get the same ID. If their amounts also match, they are identical in every published column.
- So no existing read API can reliably tell two upcoming payments apart. Getting there means publishing an existing identifier through two finance tables, which goes past "existing read APIs support it".

**3. Per-publication read permissions are real, which rules out the simplest design.**
- `/reports/<segment>` requires the permission `reports.read.publication.<segment>`, taken from the first path segment (`apps/api/auth_policies.py:393-402`). This is enforced for permission-bound principals (`tests/test_api_oidc.py:506-531`). A plain `reports.read` grant covers every publication (`permission_registry.py:390-397`).
- A route like `/reports/attention-items/{id}` that returns source rows would therefore show, say, transaction data to someone who only has attention-items permission. That would bypass role rules.
- Putting record routes under each source's own path segment gets the correct permission check from the existing middleware, with no new auth code.
- All five publications involved are `public`, and all the web pages involved require only the reader role (`nav-model.js:20,30,36`).

**4. The previous plan missed a backend ordering bug.**
- When the API serves the published copy of the attention list, the reporting service sorts it `ORDER BY severity, item_type`, i.e. lowest first (`packages/pipelines/reporting_service.py:876-882`, applied at `:1354`).
- The direct table reader sorts `severity DESC` (`transformation_overview.py:354`). So "keep the API's order for ties" isn't currently true in published mode.

**5. A clean route location exists.**
- Operating Picture fetches the current list without `as_of` (`app/operating-picture/page.js:166`), so detail pages can work on current data only.
- A route nested under `/operating-picture/` avoids the rule that every new top-level route needs a nav entry (`nav-model.js:5-6`). The repo already uses this pattern (`app/runs/[runId]`).

**6. Section-level links from the previous plan don't meet the acceptance.** They are replaced below and should not ship as the completed outcome.

## Recommended design (smallest complete version)

**Reporting layer** (`packages/domains/overview/pipelines/transformation_overview.py`):
- Define one record-key expression per type, used both to build the list and to look records up:

  | Type | Key | Source table |
  |---|---|---|
  | anomaly | `transaction_id` | `mart_transaction_anomalies_current` |
  | contract review | `contract_id` + `reason` | `mart_contract_review_candidates` |
  | contract renewal | `contract_id` + `renewal_date` | `mart_contract_renewal_watchlist` |
  | upcoming payment | **pending the HOLD decision** | `mart_upcoming_fixed_costs_30d` |

- Remove exact duplicate attention rows (`SELECT DISTINCT`). Across a record's components the attention columns are identical, so nothing is lost.
- Add a lookup function: given an item ID, return the source rows whose key expression equals it exactly. For reviews and renewals this can be several component rows of the same contract. Together they are that record's existing details.

**Reporting service:**
- Add a source-row lookup that uses the existing published-or-fallback path with a `WHERE <key expression> = ?` filter.
- Fix the attention list's published sort to `severity DESC, item_type, title`.

**API:** add `GET /reports/<source-segment>/records/{record_key}` for each source: `transaction-anomalies`, `contract-review-candidates`, `contract-renewal-watchlist`, and `upcoming-fixed-costs` once decided.
- The record key is the attention `item_id`.
- No match, a key from a different type, or a malformed key returns 404 and never another row. Responses reuse the existing row models.
- Accept keys that contain `/` (a contract ID supplied by the source can be arbitrary text). Regenerate the generated OpenAPI and TypeScript files.

**Frontend:**
- **New page `app/operating-picture/attention/[itemId]/page.js`:**
  1. Fetch the attention list and match the item ID exactly. No match goes to `notFound()`, and the page never just takes the first row.
  2. Call that type's record route and show the existing source fields with existing CSS classes.
  3. A 403 shows a "no access to <source> details" message with only the attention row. A 404 shows "no longer in the current <source> report".
- **`lib/attention-queue.mjs`**, carried over from the previous plan:
  - Rank highest severity first with a stable sort, so ties keep their order.
  - Missing or non-numeric severity counts as lowest.
  - Cut to 8 rows only after ranking.
  - Urgency labels: 3 is urgent, 2 is soon, anything else is watch.
  - `attentionHref(item)` returns `/operating-picture/attention/${encodeURIComponent(item_id)}`.
- **Existing files:** wire the module into `operating-picture/page.js` and `operating-picture-view.js`. Each row gets a descriptive link label and an `aria-label` that includes the item title. Fix the Storybook fixtures to use real item types, real domains and the correct severity direction.
- **Dropped from the previous plan:** section anchors and links into `/review` and `/utilities`.

**Out of scope:** homelab attention items, style or layout redesign, `as_of` detail pages, and `sprintctl` or database-URI changes.

## The decision needed for upcoming payments

**Recommended: option A.** Publish the existing `charge_id` as a new column on `mart_subscription_summary` and `mart_upcoming_fixed_costs_30d`. That means one DuckDB migration (`0017` is unused, or `0019` is next), two field additions in the finance manifest, regenerated contracts, and updated migration-count assertions. The upcoming item ID then becomes `'upcoming_' || charge_id || '_' || expected_date`, and every test below can pass.

The alternative is to treat the published row values as the record's identity. That fails the "must not resolve to another record" test when two rows are identical, so I don't recommend it. Leaving upcoming payments without a record destination would leave the Work incomplete.

## Falsifiable tests

**Backend (pytest).** Feed synthetic contract prices and transactions through the existing loaders. The contract-price data should include a contract with two components that renews within 14 days, plus two contracts of the same type.

1. All attention item IDs are unique. Each review or renewal record appears once. This fails on base because of the duplicate renewal.
2. Two renewal records get two different IDs, and each record route returns only its own `contract_id` and `renewal_date`. The same holds for two anomalies (`transaction_id`) and two review records.
3. An anomaly ID on the renewal route, an unknown ID, a malformed ID and an ID containing an encoded `/` all return 404. None returns 500 or another row.
4. A principal with only `reports.read.publication.attention-items` gets 403 on every source record route. Adding the source permission gives 200. No credentials gives 401.
5. Lookups give the same results in warehouse and published access modes. The published attention list comes back highest severity first.
6. Keep the existing real two-domain synthetic pipeline regression: finance and utilities both present, highest severity first.
7. After the decision: two upcoming payments with the same contract name, date and amount resolve to different destinations.

**Frontend:**

8. The ranking module, run under the pinned Node:
   - Severity is in descending order.
   - Ties keep their input order.
   - Missing, null and string severities rank last.
   - If severity-3 items come last in the input, the top 8 still include all of them.
9. Production wiring:
   - A Storybook play test or Playwright test on the real `OperatingPictureView` checks row order, labels, and that each `href` is distinct and identifies its own item.
   - A test checks that `page.js` calls the ranking module before truncating.
   - The detail page renders two same-type records with their own facts, and shows the not-found and 403 states.
   - If there's no test harness for server pages, keep the data-to-props step in a small function and test that, plus a compose-smoke request to the route. Escalate only if neither is possible.

**Gates:**
- The targeted pytest files.
- `make web-typecheck web-build web-ui-test` in the new worktree, after `npm ci` with the trusted Node and make paths.
- `make verify-fast` before the PR.

## Routing

This crosses the reporting layer, the API, auth tests, generated contracts and the UI, and the auth rules are subtle. It should go to **Terra**, not Luna as the previous plan said. Escalate if:
- the generated-contract compatibility check treats new columns as breaking, or
- path-based permissions don't cover the record routes.

**HOLD.** Upcoming payments need a decision on whether to publish the existing `charge_id`; I recommend option A. With that approved, the full Work acceptance is unchanged and the plan is READY.