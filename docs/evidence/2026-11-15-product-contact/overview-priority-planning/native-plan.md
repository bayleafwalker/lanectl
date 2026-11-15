I checked the current code end to end. The known concern is mostly confirmed, and it also reaches the home page, the first-answer page and the ingest summary. I read the whole path with Read/Grep/Glob only. I ran no commands, edited nothing, created no backlog item, and nothing was implemented or released.

**Recommendation:** treat this as its own small bugfix that can be accepted on its own. Make all readers and screens show attention items highest-severity first (3 = high), with a fixed tie order. It changes no schema and no API shape. It does not touch the individual-record API (1593), and it does not narrow HLA1590. Only the owner can create the backlog item; I haven't.

## 1. What the code does today

### Where severity comes from (`transformation_overview.py:281-353`)

| `item_type` | `source_domain` | severity | Source |
|---|---|---|---|
| `anomaly` | finance | always 2 | `:298` |
| `contract_review` | utilities | the contract's review `score`: 3 expired, 2 more than 10% above average price, 1 long tenure or several contracts of the same type | `transformation_utilities.py:633-641`. Score 0 rows have no reason and are dropped (`:656`) |
| `contract_renewal` | utilities | 3 if renewing in 14 days or less (including negative days, i.e. already past), otherwise 2. The `1` branch can't happen because rows over 30 days are filtered out | `:320-327`, `transformation_utilities.py:689` |
| `upcoming_cost` | finance | always 1, only for payments due within 7 days | `:339-342` |

- **Range:** only {1, 2, 3}. The column is `INTEGER NOT NULL` with no CHECK constraint (`0001_initial_schema.sql:758-765`, `overview_models.py:25`, which documents `1=low, 2=medium, 3=high`).
- **Meaning:** every source uses higher = more urgent.
- **Labels in the contract:** the manifest only says "Priority level for the attention item" and doesn't give a direction (`overview/manifest.py:100-102`). The utilities `score` field says "rank review urgency" (`utilities/manifest.py:338`).
- **No homelab source:** `source_domain` is only finance or utilities. This matters for HLA1590.

### Identity
- `item_id` is a prefixed key (`attention_records.py:59-84`), but it isn't guaranteed to be unique. The record API returns a group of rows per key, and anomalies have no DISTINCT.
- So a tie order of (severity, type, title) doesn't fully decide the order. Items like "Upcoming payment: X" repeat the same title across dates.

### Readers and serialization

| Path | Order | Ties |
|---|---|---|
| Warehouse current (`transformation_overview.py:356-360`, via `mart_reads.py:32`) | DESC | `item_type, title` |
| Published relation and snapshot capture source (`household_reporting.py:417-421`, `reporting_service.py:1208`) | DESC | `item_type, title` |
| **Published / prefer-published current** (`attention_records.py:87-94`, used by `reporting_service.py:1335-1356` whenever the Postgres table exists) | **ASC** | **`item_type` only** |
| As-of `?as_of=YYYY-MM` (`report_routes.py:564-600`) | the stored snapshot's order (DESC) | as captured |

- In published modes, today's list (ASC) and the as-of list (DESC) come back in opposite orders.
- PREFER_PUBLISHED falls back to the warehouse (DESC) when the table is missing. So the order you get depends on the deployment mode.
- As-of has three outcomes: `current`, `snapshot` and `no_history`. Older snapshot rows are fitted to today's columns, so a value can come back null and is flagged in `incompatible_columns` (`:588`).
- **Permissions:** reader role plus a per-publication read permission keyed on the `attention-items` path segment (`auth_policies.py:387-402`, `permission_registry.py:241-247`). There is no filtering by `source_domain`. The fix leaves all of this unchanged.

### Consumers

| Consumer | Order | Label | Result |
|---|---|---|---|
| Operating Picture `operating-picture/page.js:212` plus the view `:13-20` | ASC (null last) | 1 "urgent", 2 "soon", 3 and anything else "watch" | **Backwards.** Expired contracts and renewals within 14 days are listed last and labelled "watch" |
| Home page `app/page.js:546-551` (current and as-of, `:48`, `:71`) | ASC | severity 1 gets a "warn" pill | **Backwards** |
| First answer `first-answer/page.js:242-249` | ASC, first 6 shown | 1 = "warn" | **Backwards**, and cutting the list hides the most urgent items |
| Ingest summary `ingest-summary/[runId]/page.js:239-242` | API order, first 5 shown | 1 = "warn" | Backwards label, and in published modes it shows the 5 least urgent |
| Review `review/page.js:65-69` | DESC | 3 = `status-failed` styling | Direction is right; it reuses the "failed" style for high severity. Ties follow API order |
| Console `console-view.js:38-44, 172` | DESC | 3 shown as S1 | Consistent |
| Wallboard `wallboard-view.js:102` | none | 2 or more = urgent | Consistent |
| Briefing `morning_brief_sections.py:210-258` | DESC, ties by `item_id` | 3 warning, 2 notice, 1 info | Consistent |
| Assistant `assistant_routes.py:371-412` | answer text uses the max | – | In published modes the text names the top item, but the 3 evidence rows are the 3 lowest |
| Retro `retro/page.js:278-281` | API order | – | Reads fields that don't exist (`domain`, `item_key`); a separate defect |
| Story fixture `stories/support/fixtures.jsx:51-73` | – | – | Uses 1 = urgent ("renewal in 12 days" with severity 1; the real producer would give 3) |

**Unresolved conflicts:** none in the data path. The "1 = urgent" reading exists only in four frontend files and one story fixture. No product doc defines the scale.

## 2. Proposed bugfix scope

**Severity scale:** 3 high, 2 medium, 1 low; sort highest first. This matches the producer, the schema comment, the published relation, snapshots, briefing, console, wallboard and assistant. The owner should confirm this once, because no product doc states it.

**Fixed order everywhere:** `(severity DESC, item_type, title, item_id, detail)`, comparing strings by plain code point.
- Do this as one Python sort applied after every read: warehouse, published and as-of.
- Don't do it in SQL. Postgres's default collation can order strings differently from DuckDB, so the two modes wouldn't match.
- Unknown severity (null, not a number, or outside 1–3; only possible through as-of projection or someone editing the data) sorts after all known values. Those rows are never dropped or changed.

**In scope (write):**
- `attention_records.py`: add the order function and apply it in `get_open_attention_items`, replacing `ORDER BY severity, item_type`.
- `report_routes.py`: add an optional order hook to `_rows_as_of`, used for attention items only.
- Add `item_id` as the final tie field in `transformation_overview.py:359` and `household_reporting.py:420`.
- New `lib/attention-severity.js`: a severity-only stable sort (keeps the server's tie order) and labels: 3 urgent/warn, 2 soon/warm, 1 watch/neutral, unknown "unranked"/neutral. The word "unranked" is a new label and needs the owner's approval; otherwise keep "watch".
- Use that helper in Operating Picture (page and view), the home page, first answer and ingest summary.
- Correct the story fixture's severities.
- Optionally, make the manifest severity description say which direction is urgent. That regenerates `publication-contracts.{json,ts}`.

**Out of scope:**
- The individual-record API: `get_attention_record`, `_ATTENTION_KINDS`, `attention_record_routes.py`, and the `tests/test_attention_record_*` files.
- Producer scores, adding homelab attention, headline metric/trend/no-data (all HLA1590).
- The retro field-name bug, the review page reusing the "failed" style, duplicate React keys, how the assistant parses severity, auth or domain scoping.
- Migrations, OpenAPI shape, snapshot rewrites.

**Migration and API impact:** no DDL and no change to the OpenAPI shape or generated `api.d.ts`. The only behaviour change is row order in published current reads, so the contract compatibility report should show nothing breaking. Snapshots are re-sorted when read, not rewritten.

## 3. Acceptance plan (each check must fail on base `82dbd94`)

Use real data: seed through `TransformationService` and run a real refresh, then publish to a real Postgres via `running_postgres_container` (`tests/postgres_test_support.py:56`), following `test_attention_record_api.py:899-955`. Requests go over HTTP with real OIDC-issued tokens, as the existing tests do.

1. **Published current order:** PUBLISHED-mode `GET /reports/attention-items` returns severity that never increases, and all of 3, 2 and 1 are present. On base this fails because the reader sorts ascending.
2. **Same order in every mode:** WAREHOUSE current, PUBLISHED current, PREFER_PUBLISHED current, and as-of for the captured month return the same `item_id` sequence. On base, published current and as-of are opposite.
3. **Ties and unknowns (regression guard):** at least two rows share severity, type and title but differ in `item_id`. Also set a value outside 1–3 in Postgres and check it sorts last and is still present. I can't promise the tie check fails on base, because insertion order may happen to match. Item 1 is the proof that fails on base.
4. **Frontend:** a node:test suite (`node --test` wrapped in pytest, like `test_onboarding_auto_collapse_unit.py`) renders `OperatingPictureView` with producer-shaped rows. The severity-3 row must be first and labelled "urgent", and severity 1 must be "watch". On base this fails on meaning, not on a missing import: severity 3 renders "watch".
   - The page-level sort is only checked through the helper the pages import. These are fixtures in API shape, not captured API responses.
   - Running Next.js against a live API end to end isn't covered.
5. **Anti-vacuity:**
   - Each test asserts that every source kind and every severity value is present.
   - It asserts the row count is above zero, and that the as-of status is `snapshot`, not `no_history`.
   - Permissions are unchanged: unauthenticated gets 401, a token without the permission is denied, a reader is allowed.
   - The `test_attention_record_*` files stay unchanged.

## 4. Size, time and gates

- **Lines (added + deleted, including tests, docs and generated files):**
  - Production backend: about 35
  - Frontend and fixture: about 55
  - Python integration tests: about 180–230
  - Node unit test and wrapper: about 90–110
  - Docs and generated files: about 5–15
  - **Total about 365–445**, under the 700 limit.
- **45 minutes:** writing the code and the targeted tests might just fit. The full gate won't fit in 45 minutes of wall-clock time: full Make, the Postgres integration run, Storybook/Playwright, the seven specialist reviews and CI.
- **Visual checks:** I can only confirm 36 literal Playwright `test(` calls in 4 specs and 2 pixel baselines (`storybook-ui.spec.js-snapshots/*`). Neither baseline covers the attention screens. I can't confirm the count of 55 by reading files. Take it from the Playwright runner's `--list` on base and require the same count, unchanged, on the head commit, with the same tolerances.
- **Required gates:**
  - `make verify-fast` (`Makefile:256`) plus `test-integration`. These include `verify-arch` (the architecture contract), `contract-export-check`, `web-codegen-check` and `web-contracts-check`.
  - The seven specialist reviews in `.agents/overlays/review-specialists/`: pack-boundary, semantic-ownership, stratum-coherence, test-quality, repetition-vs-abstraction, suppression-drift, god-class-file-size.
  - A product-intention pass, train/dev health, the PR with all CI green, then canonical adoption.

## 5. How this relates to HLA1590 and 1593

- **Product direction:** "most urgent utility or contract review item" and "top three to five attention items across all domains" (`initial-capability-packs-and-publications.md:195-197`). Today the Operating Picture shows the *least* urgent items first, so any "own top attention" requirement can't be met until this is fixed. That is why this is a real prerequisite.
- **HLA1590 is not narrowed:** this fix adds no homelab attention, headline metric, trend or no-data state. HLA1590 stays blocked with its full scope and is not replaced or split by this.
- **1593 is not reopened:** the per-record API, its scale and its tests aren't touched.
- **Not a retry:** this is a different objective from the exhausted attempts. An owner has to create it as a new backlog item and confirm the severity scale and the "unranked" label.