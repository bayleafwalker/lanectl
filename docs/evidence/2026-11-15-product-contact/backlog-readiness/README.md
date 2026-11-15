# Next intended product work

Source discovery below is pinned to HLA canonical b2d0fe393ac0971e906cce275e91f45e94422593.
It is delegated code inspection, not runtime/API/browser qualification. The
served pending backlog, rather than the stale handoff, supplied these items.

## HLA1592: four-kind seven-day horizon

`app/operating-picture/page.js` builds seven calendar cells from only
`getUpcomingFixedCosts`; the view passes them to `HorizonStrip`. There is no
merged horizon API or merged-feed API test. The desired four kinds remain
obligations, renewals, due exports and approvals, labelled and date ordered.

- Obligations have a dated reporting contract: `mart_upcoming_fixed_costs_30d`,
  `expected_date`, read by `/reports/upcoming-fixed-costs`. This is subscription
  cost data, not every possible household obligation.
- Utility renewals have `renewal_date` through
  `/reports/contract-renewal-watchlist`.
- `GET /control/source-freshness` has nullable `next_expected_at`, but it means
  expected source arrival; it does not establish a due-export obligation. It is
  admin-only. A reader-facing strip cannot expose it by assumption.
- Pending action proposals have creation/approval/dismissal timestamps, but no
  deadline. Creation time must not be invented as an approval due date.

Date/undated semantics, reader-safe export publication, overlap and reporting
time/as-of behavior need a contract decision before a truthful full feed can be
implemented. A two-kind strip would not satisfy the existing item. This finding
does not narrow its acceptance or assert that the UI is complete.

## HLA1587: inline source-row upload

Actual served item1587 remains the intended acceptance: uploading from a stale
row on `/sources` stays on that page and refreshes that same row; existing
`test_freshness_remediation_flow.py` coverage remains required. Root took the
unreserved existing item under reservation505 after releasing exhausted2904's
reservation503. No failed outcome was reopened or given new attempts.

Current `/sources` server rendering joins latest runs by source_asset_id; more
than one asset can share a dataset. Dataset-only links to `/upload` cannot prove
which row was repaired. The configured ingest API already binds source_asset_id
to its contract/mapping and records the asset identity.

The existing UploadCard/UploadDetectionWizard use navigating forms. The upload
proxy redirects303 to a summary on HTTPsuccess/run_id, or back to `/upload` on
error. Detection can change the selected destination; its ranking is not proof
of intended source identity. Inline behavior needs identity-safe selection,
non-navigating errors and submission, and an authoritative row reread. Ingest
201 means ingestion passed; it does not prove promotion/publication or freshness
became current. API duplicate409 and validation400 must retain their meanings.

Actual source-freshness/catalog APIs are admin-only even though frontend page
gating permits operator/admin. Preserve the existing permissions and report
their actual behavior. Existing backend remediation tests prove API behavior,
not an inline browser flow or correct row transition. Native Opus5.5 planning
is underway before any acceptance publication or implementation attempt.

Both items must remain aligned with the Household Operating Picture product
record and Kotona brief: trustworthy, traceable real household outcomes, actual
reporting contracts and source identity; no invented facts or landing shortcuts.

## Verified snapshot limitation

Both repo-scoped `sprintctl render --sprint-id468` and `--sprint-id580` fail with
`served-operation-unavailable`: render is not available through the served
catalog. The required render workflow therefore cannot refresh Git snapshots.
No local SQLite/recovery fallback was used. Served work state remains
durable-authoritative; these Git records retain the measured changes and gap.
