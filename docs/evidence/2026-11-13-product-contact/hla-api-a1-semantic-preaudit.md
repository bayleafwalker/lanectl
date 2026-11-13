# Rejected first implementation: semantic review preparation

Read-only first-party Sage inspected HLA commit
e715121610d2f49faa653f30e79e2f992270d9ff against its frozen seed
165e234268b4c9379b9587dfdd2cf0f1b2c43948. The adjacent rejected production patch
preserves the inspected implementation against canonical source9cf62cb; this is
evidence data, not accepted production code. No runtime probe was performed in
this pre-audit. A new implementation must be reviewed on its own exact bytes.

Definite source-level blocker: `get_attention_record_rows()` selects published
mode, but its unavailable branch is nested under `publication_store is not None`.
Strict PUBLISHED mode with no store therefore reaches the warehouse reader.
Before any candidate approval, use a matching warehouse record, strict published
mode and no publication store: require unavailable503 and observe no warehouse
read. A missing relation in an existing store does not cover a missing store.

Two additional cases need narrow evidence rather than assumptions:

- An old published table can exist without `charge_id`. A lookup referencing the
  missing column may escape as500. Probe the actual pre-upgrade shape in disposable
  Postgres and preserve published authority; nullable-column tests are distinct.
- A SQL-NULL assembled key is checked, but an empty component can produce a
  plausible incomplete key. Establish whether that value is admitted by the
  supported publication contract before deciding the required response. Literal
  `"None"` in a legitimate opaque contract ID must not be globally rejected.

The bounded source review found whole-key parameter binding, component grouping,
fixed relation/key expressions, slash-capable routes and safe fixed errors in the
inspected paths. Those observations neither waive the blocker nor establish real
Postgres behavior. The portable functional gate pass is recorded separately;
source suppression and planner-owned frozen lint failures remain real failures.

The active corrected-revision worker was not edited or steered by this pre-audit.
Recheck these invariants against its completed candidate; do not infer that the
new implementation contains or repairs the rejected branch's behavior.
