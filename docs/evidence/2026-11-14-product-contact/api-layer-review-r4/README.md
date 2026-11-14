The first native R4 review completed normally with a **revise** verdict. Its raw verdict, usage and native status are preserved here. It correctly found that Docker-unavailable fixtures could skip all three PostgreSQL cases while pytest returned zero. Its assertion that explicit slow selection existed only in prose was inaccurate: the second acceptance command already selected `integration and slow`. The first review prompt did not show the actual command array.

The planner added a separate stdlib gate and a third mandatory command. The original 1,173-line acceptance input and both original commands remain unchanged. The new gate requires the exact three named cases, a successful pytest process and complete JUnit evidence with zero skips, failures or errors. It is inert under ordinary collection. Forced fixture unavailability made the original selector return zero with three skips and the gate return one. An isolated unaccepted HTTP preview passed all three real PostgreSQL cases; canonical source without HTTP failed on missing routes. These are acceptance qualification controls, not implementation approval.

The parser-control script is retained verbatim from qualification and names the pre-finalization non-test-prefixed temporary filename; the final gate was renamed to satisfy the existing proposal policy. The final positive run and collection checks used the final `test_attention_record_pg_gate.py`. A fresh independent native review of the tightened proposal is required. All four HTTP kinds, worker regressions and M700 remain unchanged. Logs describe measured cases only. `/tmp` native diagnostic trees remain session-local; the selected evidence in this directory becomes cross-host-replicated when committed and pushed.

The second review was deliberately stopped after 55 seconds when root found a distinct integration incompatibility: official specification base lint checks each acceptance file independently with pytest, and the script-only helper collected no tests. Native status is failed/143; **no review verdict is inferred**. Its status, cancellation reason and official invocation error are retained. Repair must satisfy the existing per-file base check without weakening lanectl policy.

The final planner gate adds one integration-marked, non-slow wrapper. Ordinary
collection is inert; executing the wrapper intentionally requires real PostgreSQL.
It calls the same strict runner, whose child selects only the three frozen API
cases, preventing recursion. The unchanged official per-file base lint actually
returned `[]` against canonical30c. The preview wrapper passed, the forced-skip
wrapper failed, and independent workspace review passed the narrow wrapper delta.
This closes the structural incompatibility without changing original tests, either
original command or lanectl policy. Fresh native review3 remains required.

The UI preparation JSON is read-only planning, not measured implementation size or
approved source. Its 500–900-line estimate is uncertain; the actual worker diff
and full UI behavior decide any legitimate decomposition.
