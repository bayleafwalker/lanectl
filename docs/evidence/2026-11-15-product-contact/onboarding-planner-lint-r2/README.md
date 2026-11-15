# Onboarding planner acceptance lint correction

**Status: R1 is parked with both implementation attempts consumed. R2 was not
published.** [ROOT-DISPOSITION.json](ROOT-DISPOSITION.json) corrects the stale
attempt count used while preparing this packet. The historical outcome,
planner-correction text and native request/response retain that incorrect
one-attempt-remaining premise for audit; they do not authorize another attempt.

R1 a1 remains rejected and unadopted. Native source is retained on HLA branch
`lane/hla-onboarding-expand-a1` at a5da26bb45c061b5af292d6dfb919867ae40b8f7.
Its worker-only patch and exact frozen R1 release are retained here. Native
done/exit0 is distinct from the subsequent normal Ruff gate rejection.

The new acceptance ca89412670f6aa71085101f4714013d6a6a34f15328f1f64e4e094af3d27af8a
passes target Ruff and has identical non-import AST and normalized import aliases.
Changed function/body and browser fixture negative controls reject as expected.
Ordinary installed-lanectl base lint was independently repeated: exactly16cases,
11controlsPASS, five named Expand failures, no errors/skips. Raw output retained.
Native review accepted these corrected bytes. The subsequent real admission
preflight refused because a2 had already run overnight: Flash timed out at2700s
and was rejected. Its source c6936969f3191f57609839526441cd521539d7c7 and actual
ledger/native result are retained in `r1-a2-rejection/`. Canonical R1 is unchanged;
the scratch R2 specification is explicitly invalidated against publication.

The preserved a1 helper was independently audited on its exact detached SHA:
seven named independent contract tests pass; four closed helper faults fail on
the intended named assertions; the actual worker pytest wrapper passes and
rejects all four faults and Node exit91. This is diagnostic evidence for rejected
a1, not candidate qualification under revised acceptance and not adoption.

Zero further implementation attempts are permitted for this outcome. Do not reset
or erase a1, promote its source, bypass the30line integrator budget, waive gates,
or claim wholeUI/hosted/product completion. Policy PR7 remains preparation only.

Durability: pushed Git will be cross-host-replicated; served work is
durable-authoritative. /tmp and the audit checkout are host-local scratch.
