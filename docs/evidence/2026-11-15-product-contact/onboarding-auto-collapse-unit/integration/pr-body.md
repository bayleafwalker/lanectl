The checklist already compacts automatically when both required core sources are active. This adds unit coverage of that production rule by compiling and rendering the real component and source definitions, plus an ordinary pytest wrapper with explicit missing-tool, timeout and failure handling.

The change adds two test files (159 lines) and preserves existing frontend files and baselines. The documented mounted-state seam uses real React and Next Link; hydration, storage and Expand behavior are outside this unit’s scope. Existing locked `esbuild` supplies the compiler.

Validation: full `make verify-fast` passed, including 2,756 fast tests, adapter/documentation/architecture checks, build/type checks, all 55 unchanged visual checks and Helm lint. The Node suite passes 10 cases; disabling only auto-collapse makes exactly three semantic cases fail with seven passing. Independent wrapper error-path probes and native specialist review found no blocker.

Served work: `homelab-analytics#1597` (sprintctl).
