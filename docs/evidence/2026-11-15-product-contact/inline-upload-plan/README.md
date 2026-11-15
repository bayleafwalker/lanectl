# HLA1587 inline source-row upload: planning

Existing intended backlog item1587 is active, reservation505 owned by the current
root session. No implementation release, acceptance binding or product adoption
exists. Source is canonical HLA b2d0fe393ac0971e906cce275e91f45e94422593.

Native Opus5.5 completed the first read-only plan. The external supervisor tool
session ended143; its ordinary CLI result JSON was not captured. The actual
provider end_turn response was recovered from this task's own session history;
only final text and per-message usage metadata are retained, not reasoning.
The source clone was verified clean. This is planning evidence, not an ordinary
CLI success or runtime implementation proof. The exact unit is terminal.

The draft is NOT approved: it hard-blocks XLSX/no detection even though actual
configured ingest and pinned dry-run both accept XLSX and JSON. Detection can
return no candidate or another primary while a valid pinned dry-run is ready.
Both normalize via file_format.py then map and validate actual rows; readiness
is not provenance, dedup, consistency/promotion or end-to-end ingest proof.
The draft also misplaces root acceptance outside the byte-bound release and
suggests cutting tests to fit the budget. A native planning follow-up is running
to correct these issues, preserve supported formats, immutable row identity,
explicit named-target action, full required coverage and frozen acceptance.
The followup uses systemd-managed owned stdio files to retain native output even
if the outer capture supervisor ends. See followup-live.json for its exact unit.

The unchanged existing backend target was actually run on host:
make test-target TEST='tests/test_freshness_remediation_flow.py -x --tb=short'
Six tests passed in2.97s. This does not prove inline browser/Next behavior,
configured XLSX/JSON integration, or freshness current without a schedule.

The initial sandbox target stalled. A bounded minimal credential-free FastAPI
TestClient request independently stalled there and returned200 outside it.
Only the verified owned Python test process was stopped via pidfd; its interrupted
run is not a pass. No test, timeout, baseline, dependency or permission changed.

HLA2904 remains parked/exhausted with both actual attempts retained and no new
revision publication. This is distinct original source-remediation work, not an
extra onboarding attempt. Policy PR7 remains preparation only.

Durability: pushed Git is cross-host-replicated. Served work is
durable-authoritative. Live native process state and /tmp remain host-local.
