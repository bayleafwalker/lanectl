# Immutable final implementation review

Scope: seed e231f870ceb3283278ec877033d892b8bd2b960a to head
7a26443e988587755bcb82efd3b6913e4c4d0659, read only through Git objects.
No product tests, changing worktree, providers, gates or effects were accessed
by the reviewer. This is independent terminal-source review, not the seven
native specialist candidate gate or source approval.

Blocking findings:

1. M700 exceeded:895 additions+47 deletions=942 across8files,242overbudget.
   Worker tests count; a smaller insertions-only calculation cannot qualify it.
2. components/source-row-upload.js138–150 ignores response message, observation
   and observed_latest_run_id. A superseded receipt can display 'Upload landed.
   Fresh.' and replace selected latest history with its older receipt.
3. Component68–69 initializes local run/date from props only;148–150 installs
   the receipt, clears date and calls router.refresh. Stable row key at
   app/sources/page.js149 and no prop synchronization mean updated server props
   do not reliably correct this local link/date.
4. lib/source-row-upload-model.mjs187,196–201,233–236 omits the contract-required
   message from successful/unconfirmed/rejected/duplicate response bodies.
   Existing frozen assertions do not consistently catch it.

Compared with a1, the actual upstream preview binding is preserved and checked;
network uncertainty clears file/preview, input is disabled during upload;
identity-mismatched/unconfirmed receipts no longer replace selected history;
failed catalogs close availability; actual semantic Node tests replace source
searches. Supersession and local-state synchronization remain defective.

All four declared existing test hashes and frozen acceptance are unchanged;
backend, dependencies, locks and gates have no diff. The added semantic-test
wrapper is marked slow at tests/test_hla1587_source_row_upload_unit.py31, so the
Make not-slow selection does not execute it. Separate execution evidence would
be required for a candidate. No Make, visual, train, dev or delivery run is
claimed for this rejected source.
