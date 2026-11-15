# Public optional lane image publication

Vuoro PR #326 merged the separate public optional-image publisher while preserving the default publisher byte-for-byte. All 13 CI jobs and currentness conformance passed. The actual workflow #43738166657 then published and qualified the reviewed source784c0192. See CLOSEOUT.json for exact source, artifact and image bindings.

An independent workstation readback verified both lane-main and lane-sha aliases against the same registry index digest15f84e1c, verified source/workflow provenance, pulled that exact image and recomputed its installed closure. It contains Python 3.13.18, lanectl 0.2.12 and the unchanged work/audit/knowledge/shared pins. This is actual registry evidence, distinct from the earlier local-only image. It establishes no hosted deployment, tenant migration, lane persistence/restore or event-authority cutover.

Two read-only native Sonnet source reviews and the local positive/wrong-manifest image verifier are retained. The first local all-tests invocation lacked the qualified production compiler and decoder and failed; its original log/state remain under initial-unprepared-full-suite. The existing ordinary CI profile then passed 3,651 tests with 248 skips. CI independently passed the required production-toolchain and PostgreSQL jobs. The 66 targeted tests and lint passed.

All metadata here concerns the public source and public registry artifact. Private hosted observations and their rejected disclosure are omitted. Signed download links, image layers, dependencies and generated build caches are omitted. These files become cross-host-replicated once pushed; the served acceptance decision remains durable-authoritative.
