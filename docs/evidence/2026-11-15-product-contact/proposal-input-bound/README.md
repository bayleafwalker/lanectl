# Separate trusted specification-review input bound

LANECTL2906 fixes a measured review-input defect: complete readable HLA acceptance
exceeded64KiB, while _invoke reread trusted proposal input through the parser's
model-output bound after spending the reviewer call. Trusted review input now
has a256KiB encoded-byte bound checked before checkout/dispatch. Model responses
remain64KiB and intent16KiB. The input is serialized once and verified unchanged
through a bounded opened regular-file descriptor with NOFOLLOW/NONBLOCK.
Missing, changed, reformatted, truncated, appended, symlink, directory and FIFO
inputs fail. JSON formatting by the reviewer now deliberately counts as mutation.

Actual test-first73KB failure is retained. Final worker and integrated source
each passed1140tests; target37passed. The native Sonnet5.5 static review found no
blockers. Its low-severity test-install-layout note is satisfied by the required
uv editable project setup used in both full runs; it does not manufacture a pass.
Its broader static no-race language is not a host-isolation guarantee. Existing
parent-directory/lifecycle boundaries remain; descriptor/file preservation is
the scope verified here. The actual measured rich-input need is first-party
caller data, not solely Unicode reserialization expansion.

The reviewed branch source is retained in a bundle requiring canonical ancestor
45c46d8. Source/tests were byte-compared with canonical cherry-picks. Package
version advances to0.2.14 with unchanged dependency closure; clean exact-tag
wheel/build/download/install and one actual official large-input review remain
separate required proofs. No policy, autonomy, attempts, credentials, grants,
hosted deployment or event-authority changes occurred.

Pushed Git is cross-host-replicated. Served work is durable-authoritative.
Original /tmp logs and build artifacts are host-local scratch. The HLA acceptance
draft and its candidate/product qualification remain independent and unaccepted.
