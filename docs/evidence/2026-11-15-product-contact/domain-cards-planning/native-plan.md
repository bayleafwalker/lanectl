# HLA #1590 implementation brief: one Operating Picture card per active domain

Base `b2d0fe3`. I used only Read, Grep and Glob, did not open `error.log`, and changed nothing. Plan mode asks for a plan file, but your instructions forbid edits and this session has no Write tool, so the brief is here only.

**Verdict:** the full outcome can be built on the existing reporting layer, but not inside an M700 budget (my estimate is about 1,450–1,750 changed lines). Four authority decisions are still open (Q1–Q4 below). Neither the candidate nor acceptance is green, and nothing has been run.

## 1. Current state

- **The page has no per-domain cards.** `app/operating-picture/page.js` loads ten feeds at once with `Promise.all` (lines 151–173). It shows a finance-only hero, a 5-tile freshness pulse whose tiles are hardcoded dataset names (lines 200–206), a 7-day horizon, one cross-domain attention queue, a right rail and recent changes.
  - The v2 design deliberately replaced the earlier "four domain cards" with that single hero (`docs/plans/frontend-design/implementation-prompts.html:91,125`).
- **Attention severity is shown upside down.**
  - In the data, 3 means high and 1 means low (`overview_models.py:25`). The mart sorts high first (`transformation_overview.py:321-324,348`), and the console uses the same scale (`console-view.js:38-44`).
  - The page sorts low first (`page.js:212`) and the view labels 1 as "urgent" (`operating-picture-view.js:13-16`).
  - Result: "Upcoming payment" (severity 1) is shown as urgent, and expired contracts (severity 3) are shown as "watch".
- **The page probably fails for non-admin users (inferred from code, not run).**
  - The nav shows the page to readers (`nav-model.js:20`).
  - But it calls `/control/source-freshness`, which needs admin (`auth_policies.py:941-944`, `control_routes.py:128`).
  - Any failed request throws (`backend.ts:531-533`), so the whole page errors.
- **Every fetch is all-or-nothing.** There is no per-domain way to show a failure.

## 2. What "ACTIVE" means in the code

The codebase has no "active domain" concept. There are three nearby notions:

| Candidate | Source | Problem |
|---|---|---|
| Packs loaded at runtime (`container.capability_packs`) | `builder.py:182-186`; built-in packs `builtin_packs.py:16-21` plus activated extensions `external_registry.py:247-286` | Built-in packs can't be disabled (`capability_registry.py:11-26` has no enable flag) |
| Extension pack install state `pack_installations.enabled` | `pack_lifecycle.py` | Admin-only, and it does not control runtime loading (`use_cases/pack_lifecycle.py:32-35`) |
| Adapter packs `AdapterRegistry.is_active` | `adapters/registry.py:116` | These are adapters, not domains |

**Recommended definition:** an active domain is a loaded capability pack that owns at least one source (`pack.sources` is not empty).

- Today that gives **finance**, **utilities** and **homelab**.
- **Overview** is excluded: it has no sources (`overview/manifest.py:22`) because it is the composition layer, i.e. the page itself.
- This matches the product north star of Money / Utilities / Homelab plus Overview (`docs/product/core-household-operating-picture.md:37-40`).
- A loaded extension domain with no card mapping gets an honest "no Operating Picture mapping declared" card.
- "Disabled" means not loaded: it gets no card, and no fake card is shown in its place.

## 3. Per-domain bindings

All reads go through `ReportingService` accessors only.

| | Finance | Utilities | Homelab |
|---|---|---|---|
| Headline | Latest month's net cashflow (`get_monthly_cashflow`, `net` in currency, `finance/manifest.py:90`). Currency comes from `household_overview.currency`, the same approach as `report_routes.py:1045-1049`; if missing, show "currency not declared" | Latest billing month's total cost, summed across utility types per currency (`get_utility_cost_trend_monthly`, `utilities/manifest.py:254,269`) | Healthy services out of total (`get_homelab_roi`: `healthy_service_count`/`service_count`, `overview_models.py:75-79`), as a count |
| Trend | Compared with the immediately previous calendar month, plus up to 12 months of history | Same rule as finance, for one currency only | **Not supported.** No history exists: these marts are current-only and not snapshotted (`reporting_snapshots.py:64-73`) |
| Top attention | Attention rows with `source_domain='finance'` (anomalies and upcoming costs) | Rows with `source_domain='utilities'` (contract reviews and renewals) | **Not supported.** The attention feed produces only four kinds (`transformation_overview.py:292-343`, `attention_records.py:59-80`) |
| Link | `/reports` | `/utilities` | `/homelab` (all from `nav-model.js`) |

Rules that apply to every card:

- **Attention:** an item belongs to a card only if its `source_domain` exactly equals the pack name.
  - Ranking is severity high to low, then `item_type`, `title`, `item_id`. The top item links to `/review`.
  - An item never appears in two cards. Rows with an unknown domain appear only in the cross-domain queue.
- **Trend:** only compare with the previous *calendar* month. If that month is missing, show "not comparable" rather than comparing with an older row.
  - One month of data means "no history", not a 0% change.
  - If a month mixes currencies, show partial and do not sum.
- **States, per facet and kept separate:**
  - `ok` (zero is a valid value)
  - `empty` (published, no rows)
  - `unavailable` (never published; `KeyError`, as in `report_routes.py:1075-1093`)
  - `error` (exception, isolated to that domain)
  - `partial`
  - `not_supported`
  - `unbound`
- **Provenance:** publication key, data period (latest month, or the latest `recorded_at` for homelab), and confidence `freshness_state`/`assessed_at` from `get_latest_publication_confidence` (precedent: `assistant_routes.py:502`). With no confidence snapshot, show "not assessed"; never invent a timestamp. Source freshness is never used as card content.
- **Order:** Finance, Utilities, Homelab (product order), then unmapped extensions sorted by name.

## 4. Implementation steps

### API (one attempt, with a second kept for repair)

1. **New composer** in `packages/application/use_cases/operating_picture.py`, modelled on the morning brief composer (`briefing_routes.py:44-74`).
   - Pure functions over typed inputs, with a mapping table keyed by pack name.
   - No imports from landing or transformation code.
2. **New route** `GET /api/operating-picture` in `apps/api/routes/operating_picture_routes.py`, plus a response model in `response_models.py`, registered in `app.py` next to the briefing route (`app.py:772`).
3. **Access in `auth_policies.py`:** reader role, broad `reports.read` permission and the reports-read token scope, following `/api/assistant` (`auth_policies.py:648-652`).
   - Don't put it under `/reports/`: that would create a fake per-publication permission named "operating-picture" (`auth_policies.py:393-402`).
   - Requiring broad `reports.read` stops tokens limited to one publication from getting data they couldn't read directly (`permission_registry.py:393-397`).
4. **Regenerate** the OpenAPI types (`generated/openapi.json`, `api.d.ts`) and the contract export.

### UI

5. **`backend.ts`:** add `getOperatingPictureDomains()`.
6. **`page.js`:**
   - Fetch source freshness only when `user.role === "admin"`; otherwise pass `null`.
   - Fix the attention sort to high severity first.
7. **View:**
   - Add a domain-card grid right after the hero, as an `<ol>` with an `aria-label`.
   - Each card shows a heading, value, unit, period, delta text plus the sparkline, top attention and a link.
   - Hide the freshness pulse when its data is `null`.
   - Fix the severity labels (3 = urgent, 2 = soon, 1 = watch).
8. **CSS:** reuse the `.pulseGrid` pattern and its 920px breakpoint (`globals.css:776,1439`), collapsing to one column on mobile.
9. **Keep unchanged:** the hero, the `.heroNumber` text, and the `V2Layout`/`EmptyState` stories.

### Docs

10. Add **ANA-11** and its traceability row to `requirements/analytics-and-reporting.md`.
11. Add a short section to `docs/architecture/data-platform-architecture.md`. Don't create a new architecture file: new files would need classifying (`test_architecture_contract.py:103`).

## 5. Tests

**Existing tests that must stay green, unchanged:**
- `storybook-ui.spec.js:117` (hero net "1,600.00")
- The `V2Layout`/`EmptyState` play checks
- `test_attention_record_*`, `test_reporting_api_app`, `test_morning_brief`, `test_briefing_api`
- The architecture contract
- `test_web_auth.py:1301`
- The two screenshot baselines (`storybook-ui.spec.js-snapshots/`)

**New tests that must fail on the base commit:**
- **Domain set:** Python tests seeded through a `TestClient` with real DuckDB rows, as in `test_briefing_api.py:73-90`.
  - The set and order are exactly finance, utilities, homelab, with overview absent.
  - A fake extension pack shows as `unbound`.
- **Finance values:** exact Decimal net, delta and series.
  - One month gives no trend.
  - A month gap gives "not comparable".
  - A net of 0 is `ok`, not `empty`.
- **Utilities values:** a single currency sums across utility types; mixed currencies give `partial`.
- **Homelab:** the headline is right, and trend and attention are `not_supported`.
- **Attention isolation:**
  - Finance's top item is the severity-2 anomaly, not the severity-1 payment.
  - Utilities' top item is the severity-3 renewal.
  - A "loans" row appears in no card.
  - Ties sort in a stable order.
- **Failure states:** `empty`, `unavailable` and `error` are distinct, and an error in one domain leaves the others `ok`.
- **Provenance:** present, and `null` when there is no confidence snapshot.
- **Determinism:** the same request gives the same output.
- **Access:** a reader gets 200, and a token limited to one publication gets 403. Add `("/api/operating-picture","reader")` to `test_architecture_contract.py:1107-1139`.
- **No shortcuts:** check that the composer imports no landing or transformation modules.

**New UI tests (Playwright on Storybook, using `ops-console.spec.js:21-36` as the pattern):**
- Stories: Full / EmptyDomain / NoHistory / DomainError / Partial / Unbound / Reader (no freshness pulse).
- Each story: an axe accessibility check plus exact-text assertions.
- Severity 3 shows "urgent" (this fails on the base commit).
- At 390×844, a single column with no horizontal overflow, and links reachable in order by keyboard.

**Guarding against tests that pass trivially:**
- Use different values in each domain's fixtures, so wiring the wrong data to a card is caught.
- Assert exact values, never just "it renders".
- Each of these deliberate bugs must fail at least one test: reversing the severity sort, dropping the domain filter, comparing with the previous row instead of the previous calendar month, and summing mixed currencies.

**Real-server coverage:** the API side is real (`TestClient` with seeded DuckDB). There is no harness that runs Next.js pages against a live backend. `web-build` only compiles. Whether `make verify-all`/`test-e2e-local` covers pages is unknown.

**The "55 visual checks":** I count 36 `test(` declarations; they expand through story loops to roughly that number, and there are only 2 screenshot baselines. I haven't confirmed the exact 55.

## 6. Size against M700 (estimate)

| Part | Lines changed |
|---|---|
| Composer, route, model, access rule | ~380 |
| Generated OpenAPI/TypeScript and contract export | ~200–350 |
| `page.js`, view, CSS, backend helper | ~260 |
| Stories, fixtures, Playwright | ~280 |
| Python tests | ~320 |
| Docs | ~40 |
| **Total** | **~1,450–1,750, about twice M700** |

Adding homelab trend and attention would add roughly 350 more.

Fitting M700 would mean dropping tests or states, which is the narrowing you ruled out. So it doesn't fit as specified.

## 7. Blocking questions

**Q1. Budget (blocks starting).**
- (a) Raise the budget to about 1,800 lines for one PR. **I recommend this.**
- (b) Split into two sequential PRs under this outcome: API, contract and tests (~900), then UI (~750). That uses both implementation attempts on first delivery and leaves no repair attempt.
- (c) Exclude generated files from the count. That still leaves about 1,300, over budget.

**Q2. ACTIVE definition (needs authority sign-off).**
- Confirm "loaded and owns a source", as in section 2.
- Also decide: should an extension pack whose install record says disabled, but which is still loaded, be hidden? Install state doesn't affect loading today, and `pack_key` isn't guaranteed to match the pack name. I recommend showing it, with a disclosure.

**Q3. Homelab gaps.**
- (a) Accept honest `not_supported` for homelab trend and attention. **I recommend this,** with a follow-up item to add them.
- (b) Make them prerequisites: a new attention kind for unhealthy services (mart change, a record kind and route, tests), plus a monthly snapshot schedule for homelab. Snapshot months are tied to the cashflow month (`reporting_snapshots.py:12-13`), which is the wrong clock for homelab.

**Q4. Layout.**
- (a) Add the card grid below the hero, keeping the pulse for admins only. **I recommend this:** the existing checks stay unchanged.
- (b) Replace the hero with the grid. That breaks `storybook-ui.spec.js:117` and goes against the v2 design.

Fixing the severity inversion (affects queue and cards) and making the freshness fetch admin-only are both included in scope by default.

## 8. Product direction (final pass)

- **Supports the outcome:** the north star of Money / Utilities / Homelab plus Overview (`core-household-operating-picture.md:37-40`).
- **Conflicts:**
  - **v2 design.** It says "one number, one trend, one decision", with the hero replacing the domain cards (`implementation-prompts.html:91,125`). Resolution: Q4(a) adds the cards without removing the hero.
  - **"Domain slices should feel complete"** (`core-household-operating-picture.md` §3.4). Homelab can only show a headline, so its card makes that gap visible rather than hiding it, which is the intended honesty. It still needs a decision (Q3).
- **Backs leaving freshness out of cards:** the UX audit says the freshness pulses showing "Never" were noise (`2026-10-ui-ux-audit.md:22`).

## 9. Gates (all still to be run; none run here)

`make verify-fast` (`Makefile:256`), the unchanged visual checks and baselines, the architecture contract, the seven native specialists, the product-intention pass, train/dev health, the PR with all CI jobs (`verify.yaml`), and canonical adoption.

Reservation 507 and integration stay with root. Nothing from 1587, 1593 or 2904 was reused, and no acceptance seed was written.