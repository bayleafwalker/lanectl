# Dispatch plan: homelab-analytics#1593 (Operating Picture attention queue)

**Verdict: READY**, with one tool prerequisite for the frozen test (below). The missing behavior is real, but it is narrower than the issue says. The data already comes from two domains (finance and utilities). What's broken is the Operating Picture page: it ranks items upside down and sends every row to `/review`.

This was a read-only pass. I couldn't read the GitHub issue text itself because commands and network were off-limits, so I worked from your restatement. I also didn't consult sprint state (`.sprintctl` was excluded).

## Findings

**1. The data already comes from two real domains, but no test proves it.**
- The attention list is built in `packages/domains/overview/pipelines/transformation_overview.py:281-348`. It combines four existing tables: transaction anomalies (finance), contract review candidates (utilities), contract renewals due within 30 days (utilities), and payments due within 7 days (finance).
- It's published as public (`manifest.py:77-107`) and served by `GET /reports/attention-items` (`apps/api/routes/report_routes.py:1117`).
- The gap is in the tests. `tests/test_transformation_overview.py:237` only checks that each domain is one of finance or utilities. Its fixture never loads contract prices, so the existing tests only ever see finance items. `tests/test_household_complete_integration.py:214` only checks that the result is a list. `tests/test_reporting_api_app.py:250` only checks the HTTP status.
- The Storybook fixture invents domains that the data never produces (`"loans"`, `"sources"` in `stories/support/fixtures.jsx:51-73`). That is probably where the "not cross-domain" impression comes from.

**2. Urgency is already defined, and the Operating Picture is the only screen that gets it backwards.**
- Everywhere else, 3 means most urgent:
  - The data query sorts highest first (`transformation_overview.py:343`, `:354`). Renewals within 14 days and expired contracts get 3.
  - The morning brief maps 3 to a warning and sorts highest first (`morning_brief_sections.py:210-213`, `:239`).
  - The console comment says so explicitly (`components/console-view.js:38`: "3 = high ... 1 = low"), and it sorts highest first (`:172`).
  - The wallboard treats 2 and above as urgent (`wallboard-view.js:102`).
  - `/review` sorts highest first (`app/review/page.js:65`).
- The Operating Picture does the opposite. `app/operating-picture/page.js:212` sorts lowest first, and `components/operating-picture-view.js:13-16` labels 1 as "urgent" and 3 as "watch".
- No product decision is needed here. Five consumers already agree.

**3. Every item type already has a real destination page, all open to the same role.**

| Item type | Domain | Existing destination |
|---|---|---|
| anomaly | finance | `/review`, "Transaction anomalies" section (`review/page.js:87`) |
| upcoming payment | finance | `/review`, "Upcoming fixed costs" section (`review/page.js:187`) |
| contract review | utilities | `/utilities`, "Review candidates" section (`utilities/page.js:153`) |
| contract renewal | utilities | `/utilities`, "Renewal watchlist" section (`utilities/page.js:181`) |

- All three pages require the same minimum role, reader (`lib/nav-model.js:20,30,36`).
- There are no per-record detail pages, and the brief forbids inventing them. So "its own detail route" means the page section for that item type.
- The section headings have no `id` anchors yet.

**4. The bugs this fixes:**
- Severity-3 renewals and expired contracts sort to the bottom and are labelled "watch". Payments due this week are labelled "urgent".
- The list shows only 8 rows (`operating-picture-view.js:107`), so with the inverted sort the most urgent items can disappear entirely.
- Utilities rows link to `/review`, which doesn't show review candidates or the renewal watchlist. It's a dead end.
- Every row has the same "Review →" link text. That breaks the repo's own example rule that linked detail targets need descriptive labels (`docs/examples/ui-contracts/ui-contract.yaml:88-89`).
- A missing severity becomes 9 (`page.js:212`). Once the sort is fixed it must count as lowest (0), as `/review` and the console do.
- The Storybook fixtures use the inverted severity and the invented domains.

**5. Frontend delivery playbook: no new UI artifacts are needed.**
- This fixes behavior inside an existing surface (Operating Picture v2). It reuses existing components and CSS classes and adds no design tokens or layout.
- The files under `docs/examples/ui-contracts/` are a template, not an approved contract for this screen. Their accessibility rules (severity shown as text as well as color, descriptive link labels) are still worth following.
- The Operating Picture Storybook story has no screenshot baseline, only a text check (`playwright/storybook-ui.spec.js:117-122`). Fixing the labels shouldn't break any screenshot.

**6. Tooling:**
- The Makefile points to a pinned Node at `.tooling/node-v20.20.1-linux-x64/bin/node` (`Makefile:28`). It exists in this checkout, but `.tooling/` is gitignored (`.gitignore:8`), so new worktrees won't have it.
- `apps/web/frontend/node_modules` is missing, so Playwright, Storybook and the Next build need `npm ci` first, which needs network.
- CI does install Node 20 and runs `make verify-fast` (`.github/workflows/verify.yaml:47,60`). That includes `web-ui-test` and `web-build` (`Makefile:256`), so the JavaScript checks are real CI gates.
- The frontend has no `"type": "module"` in its `package.json`. A logic module that plain Node can run therefore needs the `.mjs` extension.
- No frontend test ran in this pass.

## Implementation scope

All changes stay in the frontend. Reporting, application, control-plane and API code are untouched, and no data schema changes. Keeping the page mapping in the frontend matches the core product doc, which keeps presentation adapters replaceable (§9).

1. **New `apps/web/frontend/lib/attention-queue.mjs`.** Plain code with no imports, exporting three functions:
   - `rankAttentionItems(items)`: highest severity first, missing severity counts as 0, and a stable sort so items keep the API's order within a severity level.
   - `attentionUrgency(severity)`: 3 → urgent/warn, 2 → soon/warm, anything else → watch/neutral.
   - `attentionDestination(item)`: the table in finding 3, with section anchors. Unknown item types go to `/review#attention-items`, the existing full list.
2. **`app/operating-picture/page.js:212`**: use `rankAttentionItems`.
3. **`components/operating-picture-view.js:13-20,107-124`**: use the urgency labels and per-item destinations, with a descriptive link label per row (e.g. "Open in Utilities", plus an `aria-label` that includes the item title).
4. **`app/review/page.js` and `app/utilities/page.js`**: add `id` anchors to the four existing sections. No content changes.
5. **`stories/support/fixtures.jsx:51-73`**: use real item types, the real domains (finance and utilities), and the correct severity direction. Extend the story's play function to check row order and links.
6. **Out of scope:**
   - Homelab attention items: no urgency rule exists, so adding them would invent one. This needs a separate product decision.
   - Changing the publication or API schema.
   - Per-record detail pages.
   - Console, wallboard and `/review` sorting, which are already correct. I didn't check `/retro`.
   - The existing contract-review scoring logic.

## Tests

**Frozen spec test** (new file `tests/test_operating_picture_attention_queue.py`, fails on base because the behavior is missing):
- Runs `attention-queue.mjs` under Node with rows in the real data shape, then checks four things:
  - The result is sorted highest severity first.
  - Severity 3 is labelled urgent.
  - Each item type maps to its page and anchor.
  - A missing severity sorts last.
- On base it fails because the module and behavior don't exist.
- It finds Node in this order: `HLA_NODE`, then `<repo>/.tooling/node-*/bin/node`, then the main checkout's `.tooling`, then `PATH`.
- **Prerequisite:** the check environment must provide Node, e.g. `HLA_NODE=/projects/dev/homelab-analytics/.tooling/node-v20.20.1-linux-x64/bin/node`. You should confirm on base that the test fails on the missing module, not on missing Node.
- I'm not proposing a frozen test that only checks source text; that would be weak.

**Regression guard** (implementation commit, not frozen, because it already passes on base):
- Load synthetic transactions and contract prices through the existing loaders (`commitments.py:105` `load_contract_prices`, `transactions.py:60`) and rebuild the tables.
- Check that both finance and utilities appear and that items come out highest severity first.
- Use the review reasons that don't depend on today's date (above market average, multiple contracts of the same type) to avoid date-dependent failures.

**Verification commands:**
- `pytest tests/test_operating_picture_attention_queue.py tests/test_transformation_overview.py tests/test_reporting_api_app.py tests/test_morning_brief.py -x --tb=short`
- Frontend, inside the worktree after `npm ci` with the pinned Node on `PATH`: `make web-typecheck web-build web-ui-test`. `make` isn't on the host `PATH`; my notes say `nix-shell -p gnumake` works, but I didn't check that this session. Otherwise CI's `verify-fast` is the authoritative gate.
- Disposable dev deploy: `make docker-build` and `make compose-smoke` build the web image, which proves the Next build without Node on the host.
- `make verify-fast` before the PR.

**Routing:** the contracts are settled and the scope is small, so this fits Luna. Move it to Terra if review finds that a reader can't reach one of the destination pages.