# Publication evidence

`release.published` preserves its original event fields. `data.provenance` is
`guarded-publish` when this invocation passed publication checks and cleared the
draft flag; its timestamp is the completion receipt. `nondraft-observation`
means reconciliation found a nondrafted release, without establishing when it
was published. Older records without provenance remain legacy-unattributed.
Only a preceding guarded receipt can establish queue duration; invalidated or
otherwise uncertain history leaves that duration unknown.

An incorrect record can be corrected by appending
`release.publication.invalidated`, naming its release and revision, the SHA-256
of the complete original event serialized with `lanectl.stream_store.encode`,
a reason, and an `evidence_ref` in the form
`git:<full-40-character-commit>:<repo-relative-regular-file>`. Identical event
contents share a fingerprint and are invalidated together. Append validates the
preceding matching event and verifies the committed file in `LANECTL_HOME`;
evidence from another repository must first be committed there. This verifies
neither the author's authority nor the substance or replication of the proof.
Readers and history replay do not require Git objects. Invalidations preserve
raw history and never undo operational attempts or decisions.
