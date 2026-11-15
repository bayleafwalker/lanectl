# HLA #2908: reviewed candidate parked

The A2 candidate violates the agreed cross-consumer Unicode ordering contract. With identical recognized integer severity `3` and `item_type`, both exact titles fit the production warehouse schema: fullwidth `Ａ` (U+FF21) and emoji `😀` (U+1F600). The actual Python helper orders `Ａ, 😀`; the actual JavaScript helper orders `😀, Ａ`, including when input order is reversed. Python follows Unicode code points; JavaScript's string comparison follows UTF-16 code units. This is a reproduced valid-row counterexample, not a malformed-input assumption. See [the actual outputs and source hashes](falsifiers/confirmed-results.json).

The real briefing provider also interprets the string `"3"` as `warning` while the canonical helper marks it unknown; `"high"` raises `ValueError`. `True`, `None` and integer `7` return neutral `info`, and recognized integer controls retain `warning/notice/info`. These are data-only `BriefInputs` / `PublicationInput` provider tests. Current mart severity is `INTEGER NOT NULL`: in the measured DuckDB seam, `"3"` stores as integer `3`, `True` stores as integer `1`, and `"high"` / `None` are rejected. This does **not** establish raw malformed severities reaching an ordinary typed published read. Postgres coercion, deployed behavior and malformed historical JSON reachability were not measured.

The literal route-size blocker remains unresolved: `apps/api/routes/report_routes.py` grew from 1,257 to 1,263 lines, exceeding twice the next-largest route file's 621 lines. Much of this size debt predates this candidate. Its small growth and the review's threshold ruling are retained without a waiver. Architecture placement, duplicated Python/JavaScript semantics, repeated sorting and the remaining test-quality advisories also remain recorded in the [seven original reviews](reviews/).

Both original native attempts are used. Integrator revision 1 has no `model-error` repair authority. A2 was parked after review; served HLA #2908 is blocked, blocker event `6785` is recorded, reservation `510` was released (event `6786`), and the selected served readback shows no active reservation or terminal decision. No fix, extra attempt, waiver, adoption, specification or budget reset, train, deployment, or product landing was performed for this closeout.

## Preserved evidence

| Attempt | Model | Native outcome | Candidate added + deleted | Original gates | Frozen acceptance | Disposition |
|---|---|---:|---:|---|---|---|
| A1 | OpenCode Go / DeepSeek V4.1 Flash | timeout, exit 124 | 681 / 700 | all five passed | all 53 passed | rejected; original second attempt remained |
| A2 | OpenCode Go / DeepSeek V4 Pro | done, exit 0 | 651 / 700 | all five passed | all 53 passed | parked after reproduced review failure |

The five original gates are `diff-policy`, `fail-on-base`, `acceptance-on-base`, `acceptance` and `job:ruff`. These passing results remain passing evidence. Coverage was incomplete: they did not cover the reproduced Unicode divergence, and passing checks do not change either candidate into an accepted outcome. The frozen 1,884-line first-party gate is a **seed acceptance artifact**, separate from A1's 681-line and A2's 651-line implementation diffs. It was neither changed nor counted as candidate implementation for closeout.

Later full `make verify-fast` on exact A2 source passed: 2,768 fast tests plus 120 subtests, 60 SQLite adapter checks, 21 documentation checks, 14 agent checks, 101 architecture checks, all 55 unchanged UI checks and Helm lint. The unchanged Make target deselected 35 slow tests and reported five warnings; no skip or waiver was added. Ruff, mypy (403 source files), contract export, code generation, token/transport checks, frontend build and type checks also passed. All 1,310 candidate and 1,304 canonical tracked contents and literal modes were preserved. All 28 observed owned processes exited and the Storybook listener closed. See [the normalized runtime proof](runtime/full-make.json) and [log](runtime/full-make.log).

All seven native specialists used Claude Sonnet 5.5 through the intended review route. Their original findings and trailing prose are retained byte-for-byte. Statements that runtime was unobserved describe the review's earlier snapshot; the later actual full-Make proof closes that evidence gap only. It does not erase their remaining findings or establish candidate acceptance. The factual falsifier author also authored the external acceptance gate and does not claim independent semantic review authority.

## Sources and reproduction

Base: `82dbd9477029d6fda7df67edc617f45a1a4ceb59`.

- A1: seed `45db10004f33b8a51a03cb93990b314fea411fc1`, candidate `8556f11ec6f85b2bee9b83c68a72ef8fce623d7a`, [bundle](source/a1.bundle) / [numstat](source/a1.numstat).
- A2: seed `6075e9eab5dd83841cb10894b99480fee8a6f810`, candidate `8652b1b73aa809ff1e137b982e69faf5c7533647`, [bundle](source/a2.bundle) / [numstat](source/a2.numstat).

Each bundle was rechecked in a fresh empty bare repository after fetching only the base. Seed and candidate were absent before import; exact heads restored and strict fsck exited zero. Original and closeout restore proofs are under `source/`. Bundles preserve source; they do not imply adoption.

The factual probes load the actual Python helper, actual JavaScript helper through the existing locked esbuild dependency, and actual briefing provider. They contain no rewritten comparator or mocked production function. Check out exact A2 source and install its locked dependencies in an owned checkout. From that checkout, set `EVIDENCE` to this evidence directory and use its Python and Node runtimes:

```bash
PYTHONPATH="$PWD" .venv/bin/python "$EVIDENCE/falsifiers/probe.py"
HLA_CHECKOUT="$PWD" node "$EVIDENCE/falsifiers/probe.cjs"
```

Runtime library setup remains environment-specific. Probe copies normalize only checkout/evidence paths; original SHA-256 lineage is in [lineage.json](lineage.json). Full execution environments, native operational payloads, session/machine identities and private paths are excluded. [Secret-scan and replay checks](checks.json) cover this selection. `manifest.json` binds selected file bytes.

This is a prepared public selection. Its files become cross-host-replicated Git evidence only when the coordinator publishes them; source worktrees and original bundles remain untouched. Served work state is durable-authoritative as recorded in [the exact selected readback](state/served-blocked-readback.json).
