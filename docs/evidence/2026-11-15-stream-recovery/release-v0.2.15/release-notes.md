Explicit stream backup and verified fresh restore preserve complete SQLite events and idempotency batches, including committed WAL state. Bounded artifacts require private owned paths and restore only into new destinations. Restore verifies exact logical rows and the closed WAL header before durable no-replace publication, and reports post-publication failures without hiding existing effects.

Validation: 1,217 workstation tests, 77 focused recovery tests, independent first-party and native Sonnet reviews, separate-process WAL/replay/conflict/continuation and kernel fsync failure proof. Actual Ubuntu full-suite CI passed all 1,217 tests with zero errors or skips; first-run shell-fixture failures and actual dash red/green diagnosis are retained. Two clean offline wheels match exact source runtime bytes.

No schema, import/configure, authority, hosted deployment, backup custody, retention or RPO change. The 300-second limit covers online copying, not all validation.
