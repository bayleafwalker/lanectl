# Released owner recovery tools

Version0.2.15 is published and installed from exact source `d64fb00b7bacdb36d35c7001decf03c3e01bec58`. [PR8](https://github.com/bayleafwalker/lanectl/pull/8) landed by fast-forward after [actual Ubuntu CI](https://github.com/bayleafwalker/lanectl/actions/runs/43758032552) passed all1,217 tests with zero failures, errors or skips. The downloaded JUnit ZIP hash and actual counts are retained in `ubuntu-ci-proof.json`; the earlier failed run remains separately attributed in the parent directory.

Two clean offline wheels are byte-identical: SHA256 `457c5141762c32383e2c63b63a70e31db304c3706c4221c60e99aa435cf334f8`,234107bytes. All63 runtime files match exact source. The three [public release assets](https://github.com/bayleafwalker/lanectl/releases/tag/v0.2.15) were downloaded byte-equal, and both isolated and external installed environments matched every runtime byte. Actual CLI backup/restore and reopen proofs passed against both installations, including committed WAL, both tables, replay/conflicts/continuation and real kernel fsync failure. Raw fixture prefixes are normalized in selected runtime proofs; original hashes remain in `lineage.json`.

ServedLANECTL2910 is accepted by decision489 and reservation512 is released. `CLOSEOUT.json` is the exact evidence object used for the served decision. The release SHA256SUMS covers the public wheel and manifest; `retained-sha256.json` covers retained evidence here. The wheel itself is retained in the public release assets.

This qualifies owner source and native disposable recovery. It establishes no OCI-service recovery, hosted custody, retention/RPO, activation or event-authority cutover. Canonical integrator revision1 and exhausted product attempt limits remain unchanged.
