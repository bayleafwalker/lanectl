# HLA1587 independent acceptance draft

First-party Terra authorship; parent review and adoption required. No implementation or release is implied.

## Proposed BFF contract

`POST /sources/{source_asset_id}/dry-run` returns JSON with `ready`, `target` (`upload_path`, `source_asset_id`, `confidence_label`), `row_count`, `issues`, and `detection.format`. `POST /sources/{source_asset_id}/upload` returns JSON with `outcome`, `message`, and, when applicable, `run_id`, `status`, `row_count`, `issues`, `promotion`, and `freshness_state`. Neither redirects. Both bind the path ID and reject smuggled bindings. Upload outcomes: `landed`, `landed_unconfirmed`, `identity_mismatch`, `rejected`, `duplicate`, `outcome_unknown`, `auth_required`, `forbidden`, `unknown_source`, `malformed_request`.

Without a direct authoritative run receipt, preserve the upstream status and describe mutation outcome as unknown, regardless of the latest row. With a receipt, verify its actual run context; supersession is an observation, not an identity mismatch. Freshness does not establish publication. Never retry uncertain mutation. Known issue codes use safe templates and validated structured fields; unknown issues, raw detail, errors, exception text and promotion skip reasons are not echoed. CSV, XLSX and JSON remain supported independently of advisory detection.

## Required case IDs

NB1–NB17, RB1–RB11 and RP1–RP10 follow the corrected plan and ROOT-DISPOSITION.md. NB4 missing or superseded latest row is an observation or unconfirmed state; NB7 both pointer observations remain unknown. Additional cases cover encoded opaque IDs (`test_rb_opaque_source_identity`, `test_nb_opaque_source_identity[dry-run]`, `[upload]`), empty ID availability (`test_nb17_availability_states[empty-words5]`), free-form catalog values (`[free_string-words6]`), and nonmutating no-JS behavior (`test_rp_inline_feature[RP-nojs]`). Actual run context establishes identity. RB and ordinary upload are base-positive; candidate NB/RP behaviors require a candidate. Infrastructure, hash, population or cleanup failure is never semantic red. The full product gates and two-attempt limit remain unchanged.
