# Rejected HLA1587 acceptance R2

First-party Terra authored this acceptance, independently reviewed by the read-only acceptance reviewer. The root integration owner rejects publication. Final source449b4e95f93ece2d34b06550daae03f2df559a80d579807bbcfe6f025abe03a4 and outcome1800c8b28c6bb81bacd6c2c8dd3c1521a25bc5f5ce2d3878a1cf72bd13672eb5 remain unchanged in this archive.

R2 materially repaired the six earlier R1 defects. Its actual unchanged-base qualification is75cases:28passed47missing-feature failures,0errors/skips, in native and forced-Docker page modes. This is no candidate pass. Independent review then found remaining blockers:

1. The forced-Docker suite still unconditionally needs host native Chromium for its native failure finalizer. The private browser binaries and Nix library path were present during that qualification; it does not establish a true Docker-only fallback.
2. Real browser fixtures use an ad-hoc current source or an unconfigured source; none asserts an actual stale source before inline upload. The original stale-row upload outcome can escape. R3 must include a historically successful source now stale/overdue, its old receipt before and exact returned receipt in that same row afterward, with sibling isolation.
3. Receipt-context fault cases cover201 but not rejected400/409 receipts, although the contract binds source identity to any actual receipt. R3 must test contradictory/unreadable error-receipt contexts consistently.

The R2 files are preserved rather than retroactively called accepted. R3 repair is owned scratch preparation, no published release or implementation attempt. There is no candidate green, no attempt-budget change, and no source adoption. The official reviewer has not run against R2; native Opus supplied earlier planning only.

The lossless ZIP contains every regular retained R2 file except Python and pytest caches, with member bytes/hash verified against archive-manifest.json. Root-level plain source, outcome and report are duplicated for reading. Secret scan of the uncompressed R2 tree passed with0findings before archiving. Logs contain synthetic fixture data, not product user data. Original/tmp remains host-local; pushed Git is cross-host-replicated; tracker events6747/6748 are durable-authoritative.
