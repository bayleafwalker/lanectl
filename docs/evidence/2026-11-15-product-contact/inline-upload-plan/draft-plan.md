I've finished reading and the plan is below. I used only Read, Grep and Glob, didn't edit anything, didn't run any commands and didn't delegate. The claims are checked against code at `b2d0fe3`; nothing was qualified at runtime.

# Plan: HLA#1587 — Upload-in-context from a `/sources` freshness row

## 1. What the code shows (and where the briefing was off)

- **Every `/sources` row is a configured source asset.** `build_source_freshness_views` loops over `list_source_assets(include_archived=False)` (`packages/application/use_cases/source_freshness_overview.py:61-130`). So there is no built-in-only row, and every row has a `source_asset_id`. Disabled assets do appear as rows. The freshness payload has no `enabled` flag (`apps/api/routes/control_routes.py:143-171`).
- **The current upload links don't bind the row's identity.** They go to `/upload#upload-<dataset>` (`app/sources/page.js:10-16,67`), and that card posts to a built-in route with no source asset. The configured path is the only one that binds and checks identity: `resolve_configured_ingest_binding` refuses archived or disabled assets and mismatched ids (`apps/api/support.py:70-110`), and the ingest records `source_asset_id` (`ingest_routes.py:322-350`). The mapping keys (`account_transactions`, …) also often don't match the contract dataset names, which are e.g. `household_account_transactions`.
- **Who can do what (this stays as it is):**
  - `/control/*` is admin-only (`auth_policies.py:940-952`).
  - `/config/*` requests are admin-only (`:162-163`), so `getSourceAssets` is admin-only.
  - `/ingest/*` (detect, dry-run, configured-csv) needs operator (`:979-992`).
  - `getSourceFreshness` throws on 403 (`lib/backend.ts:522-537,1287`). So an operator on `/sources` gets the existing error page and a reader is redirected (`page.js:49-52`). In practice only admins can use `/sources`.
- **Response codes:** `build_run_response` returns 409 if a `duplicate_file` issue is present, 201 if `run.passed`, otherwise 400 (`apps/api/support.py:52-67`).
  - **A duplicate still records a new run.** The run is rejected and carries a manifest (`packages/storage/landing_service.py:131-150`), so it becomes the row's latest run. Duplicates are detected by sha256 per dataset, so sending the same file for a second asset of the same dataset also returns 409.
  - **Promotion happens inside the ingest request.** The `promotion` object (`facts_loaded`, `marts_refreshed`, `publication_keys`, `skipped`, `skip_reason`) is either present or absent. No contract describes a "pending promotion" state.
  - **Freshness states** are `current`, `due_soon`, `overdue`, `missing_period`, `parse_failed` and `unconfigured`. With no freshness config the state is always `unconfigured` (`packages/platform/source_freshness.py:13-19,171-179`), whatever was landed.
- **Detection can't tell assets apart.** It ranks configured candidates by header overlap and includes `contract_id` and `column_mapping_id` (`packages/pipelines/upload_detection.py:271-292`). Assets that share a mapping look identical to it. XLSX files and unknown formats never get a candidate (`:144-150`).
- **Dry-run can be pinned to one asset.** With `upload_path=/upload/configured-csv` plus `source_asset_id`, it validates against that asset's own binding. Unknown or disabled assets come back as issues, and nothing is written (`packages/pipelines/upload_dry_run.py:158-164,227-283`).
- **The `/upload/*` routes forward cookies and the CSRF token from cookie to header** (`lib/backend.ts:401-411`). Next.js itself does no Origin check, and there is no `middleware.*`.
- **Patterns already in the codebase:** a client component calls a Next route handler and then `router.refresh()` (`components/archive-scenario-button.js`). `wallboard-live.js:107-110` puts `useRouter` in a thin wrapper so the control itself can run in Storybook.
- **Test tooling:** Playwright only runs against Storybook (`playwright.config.js`, the screenshot specs are explicit). There is no harness that runs the real Next page against a fixture backend. `scripts/capture_finance_loop_screenshots.mjs` drives the real `/sources` page against a real running instance.

## 2. Product decisions

**D1. The row decides the identity.** An inline upload always goes to `/ingest/configured-csv` with that row's `source_asset_id`. The client cannot change the target, and detection never re-targets.

**D2. A new route handler, `app/sources/upload/route.js` (POST, returns JSON, no redirect).**
- **Inputs:** it reads only `file` and `source_asset_id`, and builds a fresh `FormData` containing `file`, `source_asset_id` and `source_name="manual-upload"` (the existing default). It drops `upload_path`, `source_system_id`, `dataset_contract_id` and `column_mapping_id`.
- **Missing fields:** if `source_asset_id` or `file` is missing it returns 400 without calling the backend. This closes the unbound built-in path.
- **Forwarding:** `backendRequest("/ingest/configured-csv", {method:"POST", cookieHeader, body})`, so auth and CSRF behave exactly as they do today.
- **Classifying the result** from the HTTP status plus `run`:
  - `landed` = 201 with a run
  - `rejected` = 400 with a run
  - `duplicate` = 409
  - `error` = anything else with no run (archived/disabled 400, 401, 403, 404, 422, 5xx), keeping the backend's detail text
- **Re-reading the row:** unless the outcome was a 401 or 403, it fetches `GET /control/source-freshness` with the same cookies and finds the row where `source_asset_id` equals the requested id.
- **Response body:** `{outcome, status, run:{run_id,status,dataset_name,file_name}, issues (normalised, ≤8), detail, promotion|null, row:{source_asset_id,latest_run_id,status,landed_at,freshness_state}|null, rowMatchesRun, rowReadStatus}`.
  - `rowMatchesRun` = `row.source_asset_id === requested && row.latest_run_id === run.run_id`.
- **HTTP status:** it mirrors the ingest status.
- **No new authorisation logic.** An operator posting directly would ingest (they already can through `/upload/configured-csv`), but the re-read would 403. The result then says "source state not readable (403)" and never claims the row was refreshed.
- **Reuse:** add `export` to `normalizeIssue` in `lib/upload-route.js`. `proxyUploadRequest` stays unchanged.

**D3. A new client component, `components/source-row-upload.js`.**
- **Structure:** `SourceRowUploadControl({sourceAssetId, name, binding:{dataset_contract_id,column_mapping_id}, onRefresh})` plus a thin `SourceRowUpload` that passes `onRefresh={() => router.refresh()}`, following the wallboard pattern.
- **IDs:** every id is namespaced, e.g. `source-upload-${sourceAssetId}-file`. Don't embed `UploadDetectionWizard`: it has fixed ids and re-targets automatically.
- **Flow:**
  1. Choosing a file starts two calls in parallel: `POST /upload/detect`, and `POST /upload/dry-run` pinned to the row (`upload_path=/upload/configured-csv`, `source_asset_id=row`). Both go through the existing route handlers, and both are guarded by a request id so stale answers are ignored.
  2. The detection verdict is worked out on the client:
     - **matches:** the top candidate is `configured_csv` for this same asset.
     - **equivalent:** the top candidate is `configured_csv` for a different asset with the same `contract_id` and `column_mapping_id`. The UI says plainly: "Detection cannot distinguish these sources; this upload is recorded for `<row>`."
     - **mismatch:** anything else, including no candidate, a built-in or HA candidate, an XLSX or unknown format, or a detect error. This fails closed.
  3. The submit button reads "Upload to `<name>`". It's enabled only when the verdict is matches or equivalent, the dry-run has `ready === true`, and nothing is in flight. The wizard lets you accept a preview that has issues; the inline flow is stricter, because a rejected run would replace the row's state.
  4. On mismatch or dry-run issues, the UI shows the issues and the detected title, links to `/upload` ("Use the full upload page to choose a different target"), and sends nothing.
- **Result messages, all in the row in an `aria-live` region, all taken from the route's response:**
  - **landed and `rowMatchesRun`:** "Landed as run X". Freshness is reported as is: `current` → "Source is current". Any other state → "Freshness: `<state>`". `unconfigured` → "No freshness schedule; currency not assessed".
  - **landed but `!rowMatchesRun`:** a warning: "Run X landed, but this row's latest run is Y/none — not confirmed".
  - **rejected:** the issues plus a link to the run.
  - **duplicate:** "Duplicate content (issue message). Recorded as rejected run Y", plus the row status from the re-read.
  - **error:** the status and detail.
  - **row read failed:** a separate notice.
  - **Promotion:** absent → "No promotion reported"; skipped → the `skip_reason`; ran → "Promotion refreshed N marts". The copy keeps "Publication trust stays in reporting surfaces" and links `/runs/<id>`. It never says "published" or "current" based on a 201 alone.
- **After any outcome:** clear the file input and call `onRefresh()`.
- **Duplicate-submit protection:** the controls are disabled while a request is in flight, and a duplicate submit would get 409 anyway.

**D4. Changes to `app/sources/page.js`.**
- Add `getSourceAssets({includeArchived:false})` to the `Promise.all`. It is admin-only, like the page already is, so permissions don't change.
- Join on `source_asset_id` to get `enabled`, `dataset_contract_id` and `column_mapping_id`.
- Remove `BUILTIN_UPLOAD_PATH` and the `upload` action.
- **Actions cell:**
  - enabled asset → `<SourceRowUpload>`, on every row whatever its staleness. This matches `/upload`'s active-asset rule (`upload/page.js:99-101`).
  - disabled asset → "Source disabled — uploads are refused". No toggle, no mutation.
  - asset not in the catalog → "Source configuration unavailable".
  - These rows keep "Inspect run" and "Open run history".
- **Recovery list:** the filter becomes "enabled and not green". Its `Upload` link becomes an in-page anchor `#source-upload-<id>` pointing at the control in the table row. That makes the table row the only interactive upload per source.
- **Why the table row:** `ResponsiveTable` keys rows by `source_asset_id` (`page.js:131`), so the control keeps its state when `router.refresh()` re-sorts the row. The recovery item disappears once the row turns green, so it can't hold the control.
- Keep the strings that `test_web_auth.py:1490-1501` checks for.

**D5. Things the plan won't do:**
- no `as_of` or historical upload surface
- no changes to `/upload`, `UploadDetectionWizard`, `proxyUploadRequest`'s redirect behaviour, the auth policy, CSRF, the OpenAPI schema or codegen
- no migrations, packages or CI changes
- no "pending promotion" state
- `/control/freshness`, `first-answer`, `runs/[runId]` and `onboarding-sources.js` keep their dataset links (out of scope)

## 3. Files the lane may touch

| Path | Change | Est. lines added+deleted |
|---|---|---|
| `apps/web/frontend/app/sources/upload/route.js` | new | ~95 |
| `apps/web/frontend/components/source-row-upload.js` | new | ~220 |
| `apps/web/frontend/app/sources/page.js` | edit | ~60 |
| `apps/web/frontend/lib/upload-route.js` | export `normalizeIssue` | 2 |
| `tests/test_freshness_remediation_flow.py` | extend | ~120 |
| `apps/web/frontend/stories/source-row-upload.stories.jsx` (MSW) | new | ~75 |
| `apps/web/frontend/playwright/storybook-ui.spec.js` | add interaction tests, no `toHaveScreenshot` | ~55 |
| `tests/test_web_auth.py` | small structural additions | ~20 |
| `docs/runbooks/operator-walkthrough.md:97-98`, `docs/product/source-freshness-workflow.md` (around :192) | update | ~15 |

**Total is roughly 660 lines (range 620–720) against the M700 cap. It's feasible but tight.** If the measured diff goes over before review, cut in this order:

1. the `test_web_auth.py` additions
2. the second Storybook test

Don't cut the Python tests, the route checks or the identity policy. Only reuse existing CSS classes (`errorBanner`, `successBanner`, `warnText`, `ghostButton`, `muted`) and add no styles. That keeps the 55 baselines and their tolerances unchanged.

**If it still doesn't fit**, the honest prerequisite split is:
- **Release A:** the route handler, `upload-route.js` and the Python tests. This proves the bound ingest and the re-read contract, but users see no change. Don't call it the outcome.
- **Release B:** the component and the page.

Splitting uses up the two-attempt budget with no retry left, so treat it as a last resort. HLA#1587 is only accepted after Release B.

## 4. Tests (in the lane, run by `make verify-fast`)

**`tests/test_freshness_remediation_flow.py` (backend contract, TestClient against the real app):**
- **Strengthen** `test_upload_in_context_recovers_stale_source`: replace `"freshness_state" in recovered` with the exact value, `"unconfigured"`, since the seed has no config.
- **New, `current` proof:** seed a `SourceFreshnessConfigCreate` the way `test_source_freshness_overview.py:193` does. Then run the inline sequence (detect → pinned dry-run → configured ingest) and assert the row's `latest_run_id == run_id`, `status == "landed"` and `freshness_state == "current"`.
- **New, shared dataset and same mapping:** detection may return the other asset first. Run the pinned dry-run and ingest for the second asset. Assert only that asset's row changes and the first row stays exactly as it was. Then post the same bytes for the first asset → 409, and assert the first row now shows the duplicate run as `rejected` (pins down the duplicate behaviour).
- **New, disabled asset:** configured ingest returns 400 "disabled", and no run is created for that asset's row.
- **New, wrong target:** a file whose detection points to a different contract. The pinned dry-run returns issues (`ready is False`) and creates no runs.

**Storybook and Playwright (fixtures only):** stories for `SourceRowUploadControl` with MSW handlers for `/upload/detect`, `/upload/dry-run` and `/sources/upload`, and a stub `onRefresh`. Tests:
- mismatch or no candidate → submit disabled, and `/sources/upload` is never requested
- matches → submit → the "landed" result and `onRefresh` called once, with the story URL unchanged

These prove the component's logic against fixtures only. They don't prove the page or the backend.

**Also run:** `make test-target TEST="tests/test_freshness_remediation_flow.py tests/test_web_auth.py tests/test_source_freshness_overview.py tests/test_architecture_contract.py -x --tb=short"`, then the full `make verify-fast` (codegen, tokens, contracts, build, typecheck, `web-ui-test` with 55 unchanged baselines). No skips, xfails, noqa, type-ignores or waivers.

## 5. Root-owned real-page acceptance (frozen before the lane, not part of the release)

**Setup:** the real stack, using `python -m apps.web.main` on a standalone build plus the API with SQLite and local auth, driven by Playwright (`frontendRequire("playwright")`, as the capture script does). Seed:
- admin, operator and reader users
- two enabled assets that share one mapping
- one asset with a freshness config
- one disabled asset
- one stale row

**Checks:**
1. **Admin, matching file in a stale row:** after submit, `page.url()` is unchanged and the main frame doesn't navigate. That row's "Last ingested" links the returned `run_id`, and the sibling shared-mapping row is unchanged. Confirm with the API (`/control/source-freshness`, and the run's manifest `source_asset_id`).
2. **Wrong file and XLSX:** submit stays disabled, no request goes to `/sources/upload`, and the run count is unchanged.
3. **Duplicate:** the 409 result text matches what the re-read row shows.
4. **`/upload`:** the ordinary card and wizard still 303 to `/ingest-summary/<id>`, and the error feedback still renders.
5. **Permissions:** operator → `/sources` fails exactly as it did before (403 truth); reader → redirected to `/`.
6. **No catalog changes:** `GET /config/source-assets` and user and role listings are identical before and after.

This is real backend integration, with seeded data rather than mocks. The Storybook tests are fixture proof only. Then come adversarial review, the seven specialists plus the product-intention pass, train, dev-health, PR CI and canonical adoption, as normal.

## 6. Open questions only an owner can settle (no approvals assumed)

1. **Operator access:** the frontend's "Operator Access" label suggests operators should use `/sources`, but the API makes freshness and the catalog admin-only. Widening that needs the auth-policy owner; this plan keeps admin-only.
2. **XLSX inline:** detection can't vouch for XLSX, so the plan fails closed and sends people to `/upload`. Allowing XLSX validated by dry-run alone is a product call.
3. **Next.js-layer CSRF:** proxying cookie to header with no Origin check is an existing posture that the new route copies. Hardening it belongs to a separate security scope.
4. **Same file across assets:** cross-asset duplicate rejection, keyed by sha256 per dataset, is existing backend behaviour. The plan shows it truthfully and doesn't change it.
