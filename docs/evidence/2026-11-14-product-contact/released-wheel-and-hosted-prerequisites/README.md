# Released artifact and hosted prerequisites

GitHub release v0.2.12 now carries the wheel, artifact manifest and checksums.
Two clean offline builds from exact tag b56f9cf produced identical bytes, also
matching the installed wheel. All 62 packaged runtime source files match the
archived tag. Actual download readback matched local bytes and GitHub's recorded
asset digests. The release is not marked immutable; consumers must verify the
pinned SHA-256, not trust a download URL alone. This is artifact qualification,
not a hosted image, storage, deployment or authority-cutover claim.

Authenticated read-only catalog discovery at the previously verified issuing
gateway observed 85 operations and no lane.stream operations in the inspected
scope. A no-credential handshake was refused401 before that successful scoped
read; refusal alone was not interpreted as absence. Existing lease operations
are listed in the retained safe metadata. No run registration, claim, grant,
profile, deployment or event-authority mutation occurred. JSONL stays authoritative.

The reusable shell's optional lane composition still requires a separate pinned
manifest and Python3.13 image qualification. Source support or unit tests do not
establish a released/deployed image. The owner storage contract also requires
explicit migration, one replica, qualified persistent local/block storage,
online backup and a rehearsed quiesced restore before hosted durability claims.

The wheel is a published release asset; these source proofs become
cross-host-replicated with canonical Git push. /tmp build contexts and downloads
remain ephemeral.


The optional Vuoro lane composition source subsequently merged in PR325,
canonicalfa7a5371ff2f06b21aaf46d806e2d19e6b105c11, after all13CIchecks passed.
The checked head is its ancestor and the canonical tree is identical. Full source
qualification passed3869tests with153skips; exact implementation74f132a image
passed11bounded owner/composition groups. Vuoro#2903 accepteddecision483 and
reservation502 released. Its source worktree and branch were removed. This
completes bounded source/image qualification only; no image registry publication,
production deployment, real gateway/fullHTTPboot, persistence proof or authority
switch occurred. See vuoro-source-adoption.json and Vuoro's retained image proof.
