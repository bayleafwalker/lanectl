Trusted specification-review inputs now have a separate 256 KiB encoded-byte limit checked before dispatch. Reviewer output remains limited to 64 KiB. Proposal files are checked unchanged through bounded regular-file descriptors, rejecting mutation, symlinks, directories and FIFOs.

Validation: 1,140 tests passed on the integrated release source, test-first regression and adversarial descriptor cases, independent native Sonnet review. Two clean offline wheel builds were byte-identical; all 62 runtime files match tagged source.

No governance, autonomy, attempt-budget, credentials, hosted deployment or event-authority change. Product acceptance for the larger HLA review is separate.
