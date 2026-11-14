# HLA #1593 full four-kind UI: refined dispatch plan (planning input only)

I worked read-only from canonical `b2d0fe3`. I made no edits, ran no acceptance, delegated nothing, and did not read private code. The `attention-key.ts` / `attention-record.ts` exports below come from your frozen description. They are not landed facts, so check them against the actual new base after the prerequisite merges.

## 0. Findings from the actual code that change the plan

1. **Severity ranking is backwards in production today.**
   - **What the data says:** the producer defines 1=low, 3=high (`packages/domains/overview/pipelines/overview_models.py:25`) and already sorts `ORDER BY severity DESC, item_type, title` (`transformation_overview.py:348,359`). Renewals due within 14 days get 3, review score 3 gets 3, upcoming payments get 1.
   - **What the page does:** it sorts low numbers first, with missing values treated as 9 (`app/operating-picture/page.js:212`). The view labels 1 as "urgent" and 2 as "soon", and everything else as "watch" (`components/operating-picture-view.js:13-20`).
   - **Result:** high-severity items show as "watch" and sort to the bottom, while 7-day payments show as "urgent". It also means missing or bad severity currently gets the same "watch" label as a real 1.
   - **Consequence for the plan:** 3>2>1 fixes the presentation to match the domain fact; it isn't a new rule. The acceptance text should say so. The Storybook fixture `stories/support/fixtures.jsx:51-73` uses the backwards meaning and must be corrected.
2. **Other pages have the same reversal, outside this scope.** `app/page.js:547-550` has the same inverted sort and an `=== 1` badge. The comment in `console-view.js:38` contradicts itself. `wallboard-view.js:102` (`>=2` = urgent) agrees with the data. Recommendation: open a separate follow-up; #1593 must not touch these callers.
3. **A failed feed currently breaks the whole page.** The private `backendGet` (`lib/backend.ts:522-538`) throws on any non-OK status, so today a 500 on attention-items breaks every panel. Malformed bodies become `[]` through `getResponseArray` (`:498-506`), which shows "All clear". Both behaviours violate the full-UI obligations.
4. **The feed API contract** (`apps/api/routes/report_routes.py:564-578,1117-1125`). With no `as_of`, the response is `{"rows":[…], "as_of": null, "as_of_status": "current", "snapshot": null}`.
   - Each row has `item_id`, `item_type`, `title`, `detail`, `severity` (all NOT NULL; severity is an integer) and `source_domain`.
   - The generated response type also allows the nullable snapshot row shape (`_as_of_row_type`, `:99-106`), so a cast is never enough. The body has to be checked field by field.
   - A busy warehouse returns 503 with a `Retry-After` header (`apps/api/warehouse_access.py:51-59`). The record routes return 404 / 503 with no header (`attention_record_routes.py:66-79`).
5. **There is no JS unit-test runner.** `package.json` only has `typecheck`, and there is no vitest/jest/`node --test` in the Makefile or CI. Adding one would change dependencies, which is out of scope.
6. **The Operating Picture story has no pixel baseline.** `storybook-ui.spec.js` takes screenshots only of the shell stories. The OP story is checked by a text assertion (`:117-122`). Correcting the fixture semantics should not move any of the 55 tolerances, but confirm that against the 55-check list on the new base.

## Q1. Is a shared, pure ranking function coherent here? Yes, if it replaces existing logic.

Today the page reduces data to plain props for the view, and the view says it owns no logic (`operating-picture-view.js:22-25`). A pure module that **replaces** both the inline sort at `page.js:212` and the view's private `ATTENTION_TONE`/`attentionMeta` is real production code, not a helper invented for a test.

**Proposed new file: `apps/web/frontend/lib/attention-queue.js`.** Plain JS. No `next/*`, `server-only` or React imports. It may import only the landed `isAttentionRecordKind` and `encodeAttentionKey`.

- `ATTENTION_QUEUE_LIMIT = 8`
- `classifyAttentionSeverity(value)` returns `{ level: "urgent"|"soon"|"watch"|"unknown", tone }`.
  - Only `typeof value === "number" && Number.isInteger(value)` with a value of 3, 2 or 1 is supported (3→urgent/warn, 2→soon/warm, 1→watch).
  - Everything else becomes `unknown` with a neutral tone: `NaN`, ±Infinity, 0, 4, 8, 2.5, `"3"`, `null`, `undefined`.
  - No `Number()` conversion.
- `buildAttentionQueue(rows)` returns `{ total, items }`.
  - It sorts by supported level first, with unknown last. Equal items keep their input order through an explicit index tiebreak. That preserves the producer's `item_type, title` order; do not add a UI title sort.
  - It slices to the top 8 **after** sorting.
  - Each item carries `{ key, item, level, tone, href|null }`.
  - `href = /operating-picture/attention/${item_type}/${encodeAttentionKey(item_id)}` only when `isAttentionRecordKind(item_type)`.
  - `key` must stay unique when `item_id` repeats (for example `item_type`, `item_id` and index). Do not deduplicate.

**How to test literal JS `NaN`:** a Node-side Playwright spec (for example `playwright/attention-queue.spec.js`) imports `../lib/attention-queue.js` directly. The Playwright runner transpiles the imports, so no new dependency is needed. Two things to check on the new base:
- Playwright's loader resolves the landed `attention-key.ts` from that import.
- The module stays free of `next/*` imports.

Cases: `[NaN, 3, "3", null, 8, 1, 2, undefined, 0, 3]` plus equal-severity runs of 9 or more.

**Falsifiers:** each of these must fail the test:
- putting back `(a.severity ?? 9) - (b.severity ?? 9)`;
- a `Number(severity)` conversion that ranks `"3"` as urgent;
- a raw NaN comparator;
- slicing before sorting;
- an unstable sort or a title sort.

**Wiring proof (needed alongside the unit test):** the acceptance must check that `page.js` imports and calls `buildAttentionQueue`, and that the view neither sorts nor maps severity itself. A browser-level case on the real page with more than 8 unsorted rows must show the correct top 8.

The JSON values `"bad"` and `null` stay in the HTTP cases as "non-numeric" and "missing". Never describe them as NaN coverage.

## Q2. Can a narrow page-specific feed adapter work? Yes, without changing `backend.ts` or other callers.

**Proposed new file: `apps/web/frontend/lib/attention-feed.ts`.** Server-only use. It imports the exported `backendRequest` and Next's `redirect`, and exports `getAttentionFeed(): Promise<AttentionFeedResult>`:

```
| { status: "ok"; rows: AttentionFeedRow[] }        // rows may be []
| { status: "malformed" }
| { status: "denied" }                               // 403
| { status: "not_found" }                            // 404 (e.g. no reporting service)
| { status: "unavailable"; retryAfterSeconds: number | null }  // 503
| { status: "unexpected" }                           // anything else
```

**Transport:** call the typed `backendRequest("get", "/reports/attention-items")` with no params, so there is no `as_of` and the read is current. Through `createBackendFetch` (`backend.ts:249-271`) that gives:
- the incoming request's `cookies()` forwarded;
- `cache: "no-store"` and `redirect: "manual"`;
- no CSRF header (GET);
- the same `getApiBaseUrl()`.

No new route, no source SQL, no caller changes. `getAttentionItems` stays exactly as it is for home, wallboard, console, review, retro, first-answer and ingest-summary.

**Status is handled before the body:**
- **401:** call `redirect("/login")` outside any try/catch, so the `NEXT_REDIRECT` signal is never swallowed.
- **3xx** (manual redirect): unexpected.
- **403 / 404 / 503 / other non-2xx:** map to the status above **without reading the body into the result**. `retryAfterSeconds` comes only from a positive-integer `Retry-After` header.
- **fetch throws:** see decision D5.

**2xx body:** `json()` inside a narrow try; a parse failure means `malformed`. The checks:
- the body is a non-null, non-array object;
- `rows` is an array, and every row is an object;
- `item_id` is a non-empty string, `item_type` is a string, `title` is a string;
- `detail` is a string or absent/null (see D3); `source_domain` is an optional string;
- **`severity` is never a reason to reject the feed.** It goes to the classifier.

Pass validated rows through without reshaping their facts.

**Reuse:** if the landed `attention-record.ts` exports a status-mapping helper, reuse it. Otherwise don't edit that file. This adapter targets the list endpoint, not the record reader, so it doesn't duplicate it.

**Falsifiers:**
- 401 ends on `/login`, with no panel and no error page.
- A 200 response shaped `{}`, `{rows:null}`, `{rows:{}}`, `"x"`, invalid JSON, or a row without `item_id` each shows the feed error, not "All clear".
- 403 / 404 / 503+Retry-After / 500 each show their own sanitized state, with no `detail` text leaked and no fallback to `getAttentionItems`.
- A 200 response with `{rows:[]}` is the only case that shows "All clear".
- Mutating the adapter to use `getResponseArray`, or catching the redirect, fails the tests.

## Other files the worker would touch (all inside `apps/web/frontend/**`, `tests/**`, `docs/**`)

| File | Responsibility |
|---|---|
| `app/operating-picture/page.js` (edit) | Use `getAttentionFeed` instead of `getAttentionItems` and `buildAttentionQueue` instead of the inline sort. Pass `attentionFeed` state to the view. The other 9 fetches stay as they are. |
| `components/operating-picture-view.js` (edit) | Remove `ATTENTION_TONE`/`attentionMeta`. Render the ok-list, "All clear" only for an ok empty list, and the malformed / denied / not_found / unavailable / unexpected states. Rows link to `href`, or have no link when `href` is null. Keep the existing `Pill`, tokens, shell, focus and reduced-motion handling. Label the queue "Current report", not `monthLabel` (which comes from cashflow). |
| `app/operating-picture/attention/[kind]/[key]/page.js` (new) | Check the kind and key with the landed `isAttentionRecordKind`/`decodeAttentionKey`, or rely on `getAttentionRecord`'s own `invalid` result if it really skips the fetch. **Invalid input means no backend call.** Map the result variants (401 redirect, 403, 404 current report missing, 503 with optional Retry-After, 500 sanitized). `AppShell currentPath="/operating-picture"`. |
| `components/attention-record-view.js` (new) | A pure view: one generic renderer plus a label/column spec per kind. Covers all rows (several rows and duplicate rows render separately) and nulls as "Unknown". Decimals render as the exact strings the API returns. `current_price` is shown with its row `currency`. A non-null `market_reference` is shown accurately and needs no currency label of its own. Nothing is invented. |
| `stories/*` | Fix the OP fixture semantics. Add stories for all 4 kinds, nulls, several rows, empty, and each error state. |
| `playwright/*` | The Node-side queue unit spec, plus whatever browser, axe, keyboard, narrow and reduced-motion cases the worker owns. |
| `docs/` | A short note on what is presentation versus domain fact. |

**Must stay byte-for-byte unchanged (exact-diff gate):** `lib/backend.ts`, `lib/attention-key.ts`, `lib/attention-record.ts`, `generated/**`, dependencies, the API, and auth.

## Architecture and product-intention pass

- **Layers stay intact.** Severity is a reporting-mart fact that the UI does not recompute. Rank, top 8, tone and labels are replaceable presentation (core doc §3.2 and the "replaceable presentation adapters" line, :185). Drill-down goes to the source rows the API already authorizes ("explainability beats novelty", §3.3; overview = "few things that deserve attention right now", :40).
- **No landing-to-dashboard shortcut.** The new route reads only the existing reporting endpoints.
- **Scoped feed errors are a behaviour change.** A failed feed would now show an error in its own panel while independent panels still render, instead of breaking the whole page. That is the right reading of trustworthy output, but the acceptance must state it (D1).

## Unresolved decisions (not guessed)

- **D1. Scoped panel error vs whole-page failure** when the feed fails. Recommendation: scoped panel error. The other publications are independent facts, so this is not a fallback.
- **D2. Label for unknown severity.** Today it falls back to "watch", which wrongly equals a real 1. Recommendation: "Unknown" with a neutral tone, matching how nullable facts are shown elsewhere.
- **D3. How strict row checks should be.** Should one structurally bad row fail the whole feed, or be dropped? Recommendation: fail the whole feed; silently dropping rows is a hidden fallback. Should a null `detail` count as malformed or just absent? Recommendation: absent.
- **D4. Unknown `item_type`:** a visible row with no link, or a malformed feed? Recommendation: visible with no link. It's a future domain value, not a broken envelope.
- **D5. Network/fetch exception:** `unavailable` with no retry time, or `unexpected`? Recommendation: unavailable.
- **D6. Whether to require `as_of_status === "current"` and `as_of === null`.** This guards against snapshot rows being shown as current, at some cost to forward compatibility. Recommendation: require them; it is the actual contract.
- **D7. Invalid kind/key UI:** Next `notFound()` or an inline "invalid link" state? It has to be distinguishable from the API's 404 "current report missing". Recommendation: an inline state.
- **D8. Decimal serialization.** I did not verify what `to_jsonable` does to `Decimal`. If it emits floats, values like `17.3456` survive but trailing zeros don't. Check on the new base before freezing the precision assertions.
- **D9. Whether to fix the home/console reversal** (finding 2). Recommendation: a separate item, not #1593.

## Acceptance changes on top of the preparatory plan

1. State the 3>2>1 fix explicitly, and require the corrected fixture.
2. Add the NaN Node-side spec with the falsifiers listed above, together with the import and wiring checks.
3. Add feed-adapter status and body cases, including "a 200 with a malformed body is not all clear" and "a 401 redirect is never caught".
4. Make the exact-diff byte check on the boundary and shared files mandatory.
5. Rebind the semantic runner and ownership ledger to the exact accepted bytes, as already listed (no SRI bypass). Separately close the c87 gaps on semantic labels and non-null market reference.
6. Show that no caller of `getAttentionItems` other than `page.js` changed.

## Size risk (rough, independent estimate)

Rough sizes:
- two `lib` modules: about 150 lines;
- page and view edits: about 120;
- detail page and view for 4 kinds: about 250;
- stories: about 120;
- Playwright specs: 200 or more;
- docs: about 20.

That is roughly 850 lines or more, likely over M700 with every test, story and doc counted. This is not derived from the rejected attempts.

Ways to reduce it without cutting kinds or weakening anything:
- one generic record renderer driven by the per-kind column specs;
- one parameterized stories file;
- tests that come from frozen acceptance rather than the worker.

**Option for root:** run two reviewed outcomes, each with its own normal M700 / max-2 / 2700s budget:
- **A:** queue fix, feed adapter and links;
- **B:** the four-kind detail route.

Both still complete #1593 together. I recommend deciding this before the new-base freeze, because A on its own already fixes a real production defect.

Nothing here makes any candidate, source or UI green, and none of it is a native acceptance verdict.
