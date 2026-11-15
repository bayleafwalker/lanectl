# Immutable first implementation: rejected

Native Go Flash actually ran2700.2seconds and timed out124. The685added+deleted lines in seven files fit M700. The five recorded gates were green: diff-policy, fail-on-base, acceptance-on-base, frozen acceptance and Ruff. This is a truthful green-gate observation, not product completion or a reason to relabel the timeout as infrastructure. Native usage141steps confirms actual implementation work.

A separate read-only source review of commita3e4709 found original-outcome defects beyond the frozen gates. No active worktree or tests were accessed for that review:

1. source-row-upload.js95–108 overwrites a contradictory upstream preview target with the selected source while preserving ready. Validation provenance must be checked rather than rewritten.
2. The client changes only its local run link. Server-rendered freshness/status/date/uploaded-as/recovery cells remain old, and local run state does not synchronize later props. Any valid update mechanism must refresh the actual row observation.
3. Fetch rejection leaves the ready preview intact, so immediate resubmission is enabled; file input stays active during upload and is not reset afterward. JSON-parse failure clears preview, so that branch is not falsely reported as retaining readiness.
4. describeOutcome discards superseded/missing observations and BFF qualification, possibly presenting another latest run's freshness as an unqualified landed/current result. Every receipt, including identity-mismatched/unconfirmed receipts, is assigned to the selected row's Last ingested link. Receipts must remain inspectable without becoming confirmed source-row history.
5. Availability resolution accepts null systems/mappings/contracts reads and missing systems as available. Partial failed catalog reads must not establish verified configuration.
6. The four added Python tests only search source strings, so they do not meaningfully exercise production helper semantics.

The integrator recorded a929-character original-scope observation before the second claim cutoff through the existing supported rejection path. The source remains rejected; no model-error fix was adopted and policy PR7 remains draft. The normal second attempt uses a different model, same R1acceptance/revision, same M700, same total two-attempt budget. There is no third retry or new-revision budget.

The bundle requires canonical HLA baseb2d0fe3. A fresh isolated bare repository fetched only that base, restored the exact source/seed/frozen test, used no alternates and passed fsck strict. Branch retirement may occur after source retention; this artifact is not a source adoption. Runtime model outcome and recorded gates are retained separately from static observations. Full Make,55visuals,sevennative specialists,architecture/product-intention,train/dev/CI/canonical feature delivery remain unobserved for this rejected source.
