# Onboarding planner acceptance lint correction

R1 a1 remains rejected and unadopted. Native source is retained on HLA branch
`lane/hla-onboarding-expand-a1` at a5da26bb45c061b5af292d6dfb919867ae40b8f7.
Its worker-only patch and exact frozen R1 release are retained here. Native
done/exit0 is distinct from the subsequent normal Ruff gate rejection.

The new acceptance ca89412670f6aa71085101f4714013d6a6a34f15328f1f64e4e094af3d27af8a
passes target Ruff and has identical non-import AST and normalized import aliases.
Changed function/body and browser fixture negative controls reject as expected.
Ordinary installed-lanectl base lint was independently repeated: exactly16cases,
11controlsPASS, five named Expand failures, no errors/skips. Raw output retained.
This is planner correction preparation for R2; renewed native review is pending.

The preserved a1 helper was independently audited on its exact detached SHA:
seven named independent contract tests pass; four closed helper faults fail on
the intended named assertions; the actual worker pytest wrapper passes and
rejects all four faults and Node exit91. This is diagnostic evidence for rejected
a1, not candidate qualification under revised acceptance and not adoption.

There remains only one actual implementation attempt across R1/R2. Do not reset
or erase a1, promote its source, bypass the30line integrator budget, waive gates,
or claim wholeUI/hosted/product completion. Policy PR7 remains preparation only.

Durability: pushed Git will be cross-host-replicated; served work is
durable-authoritative. /tmp and the audit checkout are host-local scratch.
