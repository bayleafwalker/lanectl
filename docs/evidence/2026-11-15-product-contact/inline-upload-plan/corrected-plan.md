# HLA1587 corrected plan: inline upload on `/sources` rows (supersedes the first plan)

**Status:** planning only. Nothing was run or edited, and no tracker, credential, grant, dependency or deployment was touched.

**I could not read the original prompt or plan.** `/tmp/hla-inline-upload-plan-20261115/{prompt.txt,plan.md}` is outside this restricted checkout, so the read was refused. This is therefore a complete replacement plan, not an addendum. It is built from source at `b2d0fe3` and from the requirements in your message. Root should diff it against `plan.md` and keep anything from the original that this plan doesn't contradict.

---

## 1. Facts checked in the code

Each item below was read in the source, not inferred.

| # | Fact | Where |
|---|---|---|
| F1 | The file format is chosen by suffix only. `.xlsx` reads `workbook.active`. `.json` must be a non-empty array of objects, and its CSV header is the union of all keys. Everything else, including `.xls`, is passed through and decoded as UTF-8. | `packages/pipelines/file_format.py:26-32,46,64-71` |
| F2 | A dry-run with `upload_path=/upload/configured-csv` resolves the explicit `source_asset_id` regardless of detection. If that asset isn't among the detected candidates, it builds a `confidence_label:"manual"` candidate. It then runs the same normalize → map → `validate_csv_text` steps on the real mapped rows. `ready` means "no issues". | `upload_dry_run.py:158-164,227-303,372-400,138` |
| F3 | The dry-run calls `map_csv_columns` **without** the service's function registry, and it never checks whether the source system is enabled or whether the mapping's source system matches. The actual ingest does both. So a ready dry-run can still be refused at ingest. | `upload_dry_run.py:382-386` vs `configured_csv_ingestion.py:93-99,125-143`, `apps/api/support.py:140-145` |
| F4 | Configured ingest only takes the builtin subscriptions/contract-prices branch when `source_asset_id` and the other binding fields are all absent. Forcing `source_asset_id` closes that branch. | `apps/api/routes/ingest_routes.py:288-321` |
| F5 | Status codes: 201 means passed, 409 means any `duplicate_file` issue, 400 means rejected (all of these return a `run` body). Binding errors give 400 `{detail}` (asset disabled or archived, source system disabled, binding mismatch). A `KeyError` gives 404 `{error}`, and any `ValueError` gives 400 `{error}`. | `support.py:52-67,70-146`; `apps/api/app.py:235-242` |
| F6 | Promotion runs *after* the run has landed. A `ValueError` during promotion becomes 400 `{error}` with no run in the body, even though the run exists. **"400 with no run" does not prove that no run was created.** | `packages/application/use_cases/source_ingestion.py:102-128`; `app.py:240-242` |
| F7 | Duplicate detection uses the SHA-256 of the raw bytes, scoped to `dataset_name` and not to the asset. It still writes a **rejected run**. Uploading the same file to asset B after asset A gives a 409, and the message cites A's run. | `packages/storage/landing_service.py:126-150,173-193` |
| F8 | Freshness rows are one per source asset. Runs are attributed to an asset by the `context.source_asset_id` in the run manifest. Run detail exposes `context`. | `source_freshness_overview.py:88-123`; `run_management.py:57-87` |
| F9 | Permissions: `/control/*` and `/config/*` are admin, `/ingest/*` is operator, `/runs` is reader. On `/sources`, a reader is redirected to `/`. An operator gets a 403 from source-freshness, which surfaces as the existing error state. | `apps/api/auth_policies.py:888-892,941-950,980-988,994`; `app/sources/page.js:49-57` |
| F10 | The existing `/upload/configured-csv` route redirects 303 to `/ingest-summary/<id>`, or to `/upload?error=…&feedback=…`. The existing `/upload/dry-run` route forwards the whole client form and does not catch transport errors. | `lib/upload-route.js:68-79`; `app/upload/dry-run/route.js:32-36` |
| F11 | The architecture test requires any `route.js` that calls `backendRequest` to use `// @ts-check` and the typed method/path form. But `/ingest/configured-csv` and `/ingest/dry-run` declare `requestBody?: never`, so passing a typed multipart body won't typecheck. The existing pattern solves this by putting the raw multipart call in `lib/` behind a thin `route.js`. | `tests/test_web_auth.py:722-741`; `generated/api.d.ts:13928,13970` |
| F12 | The existing `/upload` wizard silently adopts the detected `upload_path`/`source_asset_id`, and lets you "Accept preview" when `ready` is false. That is existing `/upload` behavior; the new row flow will not reuse it. | `components/upload-detection-wizard.js:124-130,272` |
| F13 | There is no Next middleware. Playwright currently runs against Storybook only. A realistic full-stack seam already exists: seed data, `create-local-admin-user`, then `apps.api.main` and `apps.web.main` (standalone) in their own process groups, local identity mode, environment scrubbed of real stores. | `playwright.config.js`; `scripts/capture_finance_loop_screenshots.py:127-191` |
| F14 | Bootstrap seams: `POST /auth/login` sets the session and CSRF cookies. `POST /auth/users {username,password,role}` creates users (admin). `POST /config/{source-systems,dataset-contracts,column-mappings,source-assets}` sets up the catalog. | `auth_session_routes.py:42-88`; `models.py:164-167`; `source_*_routes.py` |

---

## 2. Corrected design decisions

### 2.1 Source identity and the role of detection
- The row action pins one `source_asset_id` taken from the freshness row. It cannot be changed inside the flow.
- The Next routes take that ID from the **path segment**. The client cannot override it.
- Detection is advisory only. The row flow makes **no separate `/upload/detect` call**. The only detection-related information it shows comes from the pinned dry-run's own `target.confidence_label` and `detection.format`.
- Having no detected candidate, or detection preferring another asset or HA states, is **not** treated as wrong data. Readiness comes only from the pinned validation.
- XLSX, JSON and CSV support is unchanged, because both routes use the existing normalizer path. There is no client-side suffix hard block. The `accept=".csv,.xlsx,.json,…"` attribute (the same as the wizard) is only a hint; the dry-run decides.

### 2.2 New Next routes (no backend or OpenAPI change)
- `app/sources/[sourceAssetId]/dry-run/route.js` and `app/sources/[sourceAssetId]/upload/route.js` are thin wrappers.
- All backend calls go in a new `lib/source-row-upload.js`. It uses raw `backendRequest(path, {…})` for multipart (the `upload-route.js` pattern, per F11) and typed `backendJsonRequest("get", …)` for reads. It never uses `backendGet`, so a 401 can't trigger `redirect()`.
- **Fields sent to the backend.** Both routes build a fresh `FormData` instead of forwarding the client's form:
  - Upload: `file` (same bytes and filename), trimmed `source_name`, and `source_asset_id` taken from the path.
  - Dry-run: `file`, `upload_path=/upload/configured-csv`, and `source_asset_id` taken from the path.
  - Everything else is dropped: `upload_path` on upload, `source_system_id`, `dataset_contract_id`, `column_mapping_id`, any second `source_asset_id`, and unknown fields.
  - The client may also send `expected_prior_run_id`. It is used only locally for the post-check and is never forwarded.
- The cookie header is forwarded, and the CSRF header is derived from the cookie as in the existing BFF. No new auth scope is added.
- **Responses are always JSON.** There is never a 3xx or `Location` header. Bodies contain only whitelisted fields:
  - `run_id`, `status`, `row_count`, `issues[{code,message,column,row_number}]` capped at 8, the backend-returned `promotion{facts_loaded,marts_refreshed,publication_keys,skipped,skip_reason}`, `freshness_state`, `outcome` and `message`.
  - `raw_path`, `manifest_path`, `sha256`, upstream error text, stacks, hosts and ports are never included.
- Missing `file` → 400 without calling the backend.

### 2.3 Outcome taxonomy (upload route)

| Backend result | Route action | `outcome` (HTTP) |
|---|---|---|
| 201 with `run.run_id` | Re-read `GET /runs/{id}` (`context.source_asset_id` must equal the pinned ID) and `GET /control/source-freshness` (the pinned row's `latest_run_id` must equal the run ID) | `landed` (201) if both match. Shows "current" only if `freshness_state==="current"`; otherwise it says it landed and states the row's actual freshness state, e.g. "no freshness schedule configured". `identity_mismatch` (201) if either check differs or the row is missing. `landed_unconfirmed` (201) if a re-read fails. None of these claim currency or publication. |
| 400 with `run` | Sanitize | `rejected` (400) with the run ID and issues |
| 409 | Sanitize | `duplicate` (409): "already landed in run X (possibly via another source on this dataset); a rejected duplicate run Y was recorded for this source" |
| 400 without `run` (`error` or `detail`) | Post-check: re-read freshness and compare with `expected_prior_run_id` (per F6) | `refused` (400) with the backend's validation message and either "no new run was recorded" or "a new run Z appeared for this source; open it" |
| 401 / 403 / 404 / 422 | No post-check | `auth_required`, `forbidden`, `unknown_source`, `malformed_request` (same status). The client shows a sign-in link; nothing navigates automatically. |
| 5xx, non-JSON, 2xx without a run, or transport failure | Generic message plus the same prior-run post-check | `outcome_unknown` (502): "Upload outcome could not be confirmed", followed by the post-check result or "couldn't confirm either". **No automatic retry.** |

The dry-run route returns 200 with the preview subset (`target`, `row_count`, `date_range`, `issues`, `issue_count`, `ready`, `detection.format`). If the backend returns an error status, it returns that status with a generic message. On a transport failure it returns 502 with a generic message.

### 2.4 Row client component (`components/source-row-upload.js`)

**Availability is computed on the server.** `page.js` adds parallel reads of `getSourceAssets`, `getSourceSystems`, `getColumnMappings` and `getDatasetContracts`. These are existing admin reads, and the page's audience is already admin, so nothing is widened. Each row gets one state:
- `available`
- `disabled`: the asset is disabled
- `source_system_disabled`
- `unsupported`: the mapping or contract is missing from the non-archived catalog
- `not_found`: the asset isn't in the catalog
- `config_unavailable`: any of those reads failed

Only `available` renders the control. Every other state shows plain explanatory text. The freshness failure behavior, the reader redirect, and the builtin `/upload#…` links are unchanged.

**Preflight:**
- Selecting a file starts a dry-run automatically.
- A `requestId` ref is bumped whenever the file changes, the selection is cleared, or the flow is reset. Responses from an older request are ignored.
- The preflight result is bound to that exact `File` object.

**Submit gate.** All of the following must hold:
- `ready===true`
- `target.upload_path==="/upload/configured-csv"`
- `target.source_asset_id===pinned` (a mismatch is treated as an error and never submits)
- the current file is the file that was preflighted
- the preflight request is the latest one
- nothing is in flight

The button is labelled **"Upload to \<source name\>"**.

**Explanations shown before submit** (truthful and deterministic):
- When `confidence_label==="manual"`: "Columns weren't automatically matched to \<name\>; the file validated against \<name\>'s mapping."
- When other enabled assets share the same `column_mapping_id`: "N other sources (\<names\>) use the same format; nothing in the file identifies which account it belongs to — confirm it is for \<name\>."
- Always: "Validation doesn't guarantee landing: duplicate, source-system and promotion checks happen on upload."

**In-flight control:**
- A synchronous `inFlightRef` is set before `fetch`. The button and file input are disabled, and repeat clicks or Enter presses are ignored.
- After any terminal outcome, the file and preflight are cleared, so resubmitting needs a new selection and a new preflight.
- A backend 409 is not treated as the duplicate guard.

**After submit:**
- The outcome is shown inline in an `aria-live` region keyed by `source_asset_id`.
- `router.refresh()` re-reads that row on the server. There is no navigation.
- There is no pending-promotion state and no as-of upload.

**No-JS behavior:** without JavaScript, no mutation is possible from the row, so ingest is never ungated. The existing upload links remain available.

### 2.5 What stays unchanged
- Backend, OpenAPI and codegen.
- `/upload`, the wizard, and the routes `/upload/configured-csv` and `/upload/dry-run`.
- Auth policies and the catalog.

---

## 3. Delivery contract

### 3.1 Frozen, byte-bound acceptance (root-owned planner seed, excluded from the worker diff)
Files live under `backlog/HLA1587/files/tests/acceptance/`, and their hashes are recorded in the lanectl release with `acceptance.exec` declared:
- `test_hla1587_backend_contract.py`: real `apps.api.main` subprocess.
- `test_hla1587_next_boundary.py`: the real built Next standalone server, pointed at an owned, scripted upstream stub that records requests.
- `test_hla1587_real_page.py` and `hla1587_sources_page.spec.mjs`: the real Next server with the real backend, driven by Playwright Chromium.
- `seeds/`: deterministic CSVs, a **committed binary `.xlsx`** (bytes frozen, hash recorded), a JSON file that includes HA-like keys, an invalid CSV, a corrupt `.xlsx`, and a non-UTF-8 `.xls`. Catalog definitions are copied from `tests/control_plane_test_support.py:84-141`, plus a second asset `bank_partner_savings` that shares the same mapping.

Rules for the acceptance files:
- They import nothing that the worker creates.
- They must be Ruff-clean on the target.
- They need a new independent native review before guarded publication.
- Extra candidate gates are bound by content hash at base: `tests/test_freshness_remediation_flow.py` (the existing six, run **on the host**; a sandbox stall is not a pass), `tests/test_file_format.py`, `tests/test_manual_upload_and_preview_api.py`, and the architecture contract.

### 3.2 Red controls on the canonical base (`b2d0fe3`, ordinary build)

| File | Expected result on base | What proves the harness is healthy |
|---|---|---|
| Next boundary | Fails semantically: the stub records **zero** upstream calls for `POST /sources/<id>/upload` and `/dry-run`, and the response isn't the JSON outcome shape | In the same run, the existing `/upload/configured-csv` → 303 parity probe passes and the stub records it |
| Real page | Fails semantically: there is no "Upload to Bank Partner Transactions" control, and the row's run never changes in place | In the same run, login works, `/sources` renders both seeded rows with their names and run IDs, and the existing `/upload` flow still works |
| Backend contract | **Passes on base by design.** It checks preserved behavior and documents the contracts the feature depends on. | It is itself the positive control |

Startup or setup failures and missing helpers never count as red. Each red is recorded with its failing assertion message. A green run on the candidate is required before guarded publication.

### 3.3 Mandatory coverage (all required; parametrize instead of cutting)

**Next boundary, real Next with a stub upstream:**
- **NB1.** Fields forwarded and dropped, with the fixed path identity, on both routes. This includes a smuggled `upload_path=/upload/subscriptions` being dropped.
- **NB2.** Cookie and CSRF headers are forwarded.
- **NB3.** 201 with a matching re-read gives `landed`, tested with both `current` and `unconfigured` freshness states.
- **NB4.** Identity mismatch, for each case: run context differs, row's run differs, row missing.
- **NB5.** Re-read failure (500, 403, transport) gives `landed_unconfirmed`.
- **NB6.** 400 rejected, with the body sanitized.
- **NB7.** 400 without a run, in both the new-run-appeared and no-new-run variants.
- **NB8.** 409 duplicate.
- **NB9.** 401 and 403 produce JSON with no `Location` header.
- **NB10.** 404.
- **NB11.** Malformed backend response: non-JSON, or 2xx without a run.
- **NB12.** Transport failure gives 502 with no disclosure.
- **NB13.** Missing file → 400 and no upstream call.
- **NB14.** No 3xx from either route, under any scenario.
- **NB15.** Ordinary 303 parity for the existing route under the same stub responses.
- **NB16.** Dry-run route: passthrough, error status, transport failure.
- **NB17.** `/sources` availability states (`config_unavailable`, `source_system_disabled`, `unsupported`, `not_found`, `disabled`) rendered by real Next against stub catalog responses.

**Real backend:**
- **RB1.** CSV: pinned dry-run is ready, ingest returns 201, `context.source_asset_id` is A, A's freshness row shows the run, B is unchanged.
- **RB2.** XLSX success.
- **RB3.** JSON: precondition that detect-source's primary is ≠ A (checked on base); pinned dry-run is ready; ingest returns 201.
- **RB4.** Same bytes to B → 409, with a rejected run attributed to B and A unchanged.
- **RB5.** Invalid content: dry-run is not ready; a direct ingest returns 400 rejected.
- **RB6.** Corrupt `.xlsx`, `.xls`, or non-UTF-8 input: dry-run is not ready; ingest returns 400 with no run.
- **RB7.** Disabled asset: dry-run issue plus ingest 400.
- **RB8.** `/config/*` and `/auth/users` snapshots are identical before and after.
- **RB9.** Operator can use `/ingest/*` but gets 403 on freshness; reader gets 403 on `/ingest`.
- **RB10.** Dry-run creates no runs.
- **RB11.** With a shared mapping, A's pinned dry-run reports A even when detection ranks B.

**Real page:**
- **RP1.** CSV in place on row A: shows a preview, the named action, and the landed outcome; row A's link becomes the new run ID; B is unchanged; the URL and page instance are unchanged (window marker survives).
- **RP2.** XLSX and JSON.
- **RP3.** Invalid file: not ready, no submit, issues shown, run count unchanged.
- **RP4.** Duplicate to B is reported truthfully.
- **RP5.** Stale preflight ignored: the first real response is delayed with `page.route().continue()`, and only the second file is shown and uploaded.
- **RP6.** Delayed real upload with a double-click or double Enter: exactly one POST and exactly one new run.
- **RP7.** A disabled row is honest and has no control.
- **RP8.** Operator sees the existing 403 error state; reader is redirected to `/`.
- **RP9.** `/upload` still lands via 303.
- **RP10.** The control is labelled with the source name and outcomes are announced through `aria-live`.

### 3.4 Harness (needed before acceptance can run)
- **Processes:** follows the capture script (F13). Candidate and base each get a `make web-local` standalone build. `apps.api.main` and `apps.web.main` run with `start_new_session` and are stopped by process group. Free ports. A temporary `HOMELAB_ANALYTICS_DATA_DIR`. `IDENTITY_MODE=local` with a test session secret. The same environment scrub as the capture script. No TestClient, which avoids the reproduced sandbox hang.
- **Bootstrap, in order:**
  1. `create-local-admin-user` (CLI).
  2. Admin `POST /auth/login`, keeping the cookie and sending `x-csrf-token`.
  3. `POST /auth/users` creating an operator and a reader.
  4. `POST /config/...` for the catalog, then a disabled third asset.
  5. Snapshot the catalog and users.
- **Stub upstream:** an in-process HTTP server, scripted per scenario, that records method, path, headers and multipart fields. Transport failure is simulated by a closed port and by a mid-response reset.
- **Remaining gaps, each unproven until an actual run:**
  - the exact `/auth/login` CSRF handshake in the standalone build;
  - Chromium being installed on the target host;
  - whether the RB3 JSON seed really makes detection prefer something other than A (the seed may need adjusting, verified on base);
  - whether real processes avoid the sandbox stall.

### 3.5 Size and split
- The default is a single item. The estimated worker diff (two thin routes, the lib, the client component, the `page.js` change and worker-side tests) is near M700. Coverage will not be cut to fit.
- If the measured diff exceeds M700, the honest split is:
  - Part A: routes and lib, plus NB1–16.
  - Part B: row UI and page, plus NB17, RB and RP.
- Neither part replaces the full in-place acceptance. The max-2 implementation-attempt budget is shared, not renewed. The two exhausted onboarding attempts stay closed and separate.

### 3.6 Gates that stay unchanged
- Full Make.
- The existing 55 matched visual checks, which must stay unchanged. No new baselines are required.
- `verify-arch`.
- The seven native specialists from `.agents/overlays/review-specialists/`.
- The product-intention pass.
- Train, dev, PR with all CI, and canonical adoption.
- Root stays integration owner (reservation 505).

---

## 4. Questions that need your authority

1. **Source types that shouldn't offer manual upload.** `asset_type` and `transport` are free strings, so the catalog can't say which sources should never offer manual upload (for example API- or MQTT-fed assets). Default: offer the action on every `available` asset and let server truth refuse. Overriding this needs an owner-defined rule.
2. **lanectl schema.** The exact lanectl `acceptance.exec` and manifest key syntax isn't in this repo. Root should fill it in using the semantics in §3.1–3.2.

Two notes outside scope (no action proposed):
- The existing wizard silently adopts detection and allows accepting a not-ready preview (F12).
- The existing `/upload/dry-run` route doesn't catch transport errors (F10).
