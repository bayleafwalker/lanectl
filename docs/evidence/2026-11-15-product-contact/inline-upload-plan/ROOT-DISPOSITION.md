# Integration-owner disposition of the corrected HLA1587 plan

The native follow-up completed successfully on unchanged canonical HLA b2d0fe3:
451.381 seconds, exit0, result success/end_turn, actual model usage only
claude-opus-5-5. This is planning, not acceptance, implementation or adoption.
Its complete replacement plan supersedes the first draft. Native restricted
reads could not reach the old draft outside its checkout; that limitation is
preserved in the response rather than hidden.

The following owner corrections are binding before frozen acceptance is authored.
They preserve the original full inline-upload outcome and existing API authority.

1. Preserve configured CSV, XLSX and JSON support. Detection is advisory and
   cannot silently change the row's source_asset_id. An explicit named-target
   action follows pinned validation. Nonready or wrong-bound preflight cannot
   mutate. Missing/other primary detection alone does not reject valid input.
   IDs remain opaque: existing creation/storage supports slash, percent and
   Unicode; multipart binding preserves the original value without trimming,
   normalization or repeated URL decoding. An empty identifier cannot bind and
   must not fall through to a built-in unbound ingest.
2. HTTP status and direct run receipts are distinct from effect confirmation.
   Without an authoritative run receipt, a latest-row snapshot cannot prove
   that no run was created or that a changed run belongs to this request.
   Promotion can fail after landing and yield a run-less400; global application
   error handling is not a typed pre-mutation receipt. Preserve the upstream
   status, describe mutation outcome as unknown/unconfirmed, and report only
   the latest observed row/run. Never say "no new run was recorded" from an
   unchanged pointer. Never automatically retry an uncertain mutation.
3. Establish this receipt's source identity from its actual run context. If a
   different upload supersedes it as the latest row, that is an observation or
   confirmation limitation, not proof of identity mismatch. A contradictory
   run context is a genuine mismatch. Freshness is the observed reread state;
   a landed run alone does not prove current freshness or publication success.
4. Whitelisting property names does not sanitize free-form upstream strings.
   Known issue codes use safe message templates and validated structured
   fields; unknown issues get a generic message. No arbitrary detail/error,
   transport text, exception/stack, or promotion skip_reason is reflected.
   Apply this to preflight, ingest and promotion. Preserve actionable known
   validation context and role/status truth without disclosing diagnostics.
5. The page keeps the existing permission boundary and configured manual-upload
   availability. Do not invent asset_type/transport restrictions from free
   strings or broaden reader/operator access to admin catalog/freshness APIs.
6. The planner freezes acceptance in the lanectl release before implementation.
   The specification proposal supports Python test files; embed browser script
   and deterministic public fixture bytes where needed, and bind every extra
   artifact. All source/fixture hashes, command declarations and provenance must
   be current. Ruff-clean ordinary base controls precede guarded publication;
   a real candidate is qualified after publication/implementation, not before.
   Startup, tool or missing-helper failures are infrastructure errors, never
   evidence of the absent inline feature.
7. All meaningful required coverage remains mandatory. Parameterization/reuse
   is welcome; tests are not cut merely to satisfy M700. A prerequisite cannot
   replace the complete original outcome or renew its total two actual
   implementation attempts. Measure the live ledger before specification review,
   revision, publication and admission: the handoff is not an attempt counter.
8. The no-JavaScript control requires an actual seeded row in the complete DOM,
   including hidden streamed content when applicable. Prove that user-actionable
   native controls cannot create an inline mutation without the preflight gate;
   selecting a file alone is not mutation, and a safe form is not forbidden.
   An empty streaming shell is not evidence of a safely disabled row control.

An independent read-only design pass identified corrections2–4 from actual
source: run creation precedes promotion in source_ingestion.py, untyped errors
are mapped by app.py, freshness exposes a latest observation, and dry-run issue
messages can contain raw exceptions. No backend/API expansion is needed for
these corrections. This is not a new policy/approval gate.

The parent has delegated a first-party, scratch-only bootstrap proof: real
production-built Next plus actual API/local auth, deterministic source catalog,
supported-format and ordinary-upload controls, source fingerprints and owned
cleanup. No candidate implementation or release exists. Its results remain
unobserved here until the worker returns and the parent inspects the evidence.

The original seven specialists, architecture contract, complete Make and55
unchanged visual checks, product-intention pass, normal train/dev-health/PRallCI
and canonical adoption remain required. Neither the plan nor the six passing
existing backend tests proves those outcomes. Onboarding2904 remains exhausted
and closed to further attempts; this is distinct original work1587.
