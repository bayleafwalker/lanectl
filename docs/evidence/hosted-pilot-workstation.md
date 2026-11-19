# Hosted pilot workstation evidence — 2026-11-19

## Scope

One hosted claim-to-outcome pilot on the workstation, using the released
`lanectl` client against the configured Vuoro Work owner for repository
`lanectl`. The pilot exercised the normal claim path for Work item 1 and then a
separate systemd credential preflight. It did not deploy a lane, migrate an
event authority, or settle Work successfully.

Release existence and Work settlement are **owner facts**. They are established
only by the release and Work owner, not by this document, a candidate, a local
journal, or the fact that an attempt ran. The observations below are a bounded
record of what the owner and the host-local coordination journal returned.

## Work #1

The pilot Work item was `lanectl#1`, titled "Verify LANECTL hosted gateway
claim-to-outcome", against release `hosted-pilot-work-1` revision 1 at base
`cb3813baa5ddf13f791b5d652711fe204440d0d4`. The owner's lifecycle read
identified authority `sprintctl` and reported the item as active.

The run and lease acquisition were acknowledged by the owner:

| Fact | Observed value |
| --- | --- |
| Run | `run_S1PDP88ATWNKX0VFDCK08N0NA8` |
| Principal | `vuoro-cloud:rnr_01M7TJQ4EQQF8NBKTVVJ91S9HV:0` |
| Workspace | `01M7TGWK6GYGKEY8HTD7PNJV88` |
| Lease | `lease_BVDWT2B73W2EDNQWJ0G7P3ZRTB`, generation 1 |
| Acquired / expires | `2026-11-19T19:01:52.334764Z` / `2026-11-19T19:11:52.334764Z` |
| TTL / heartbeat | 600 s / 120 s |

The `work.lease.acquire-v1` response returned that lease as active. This is an
acknowledged acquisition, not merely a locally cached claim.

The client appended three evidence observations to the owner chain and received
the corresponding owner-side items:

| Sequence | Item | Digest |
| --- | --- | --- |
| 0 | `hosted-pilot-work-1-a1:claim` | `sha256:3b6dd913d0353c766a8e90de683154bf27c1e7149cf3f8616cfdb1ece827a2c2` |
| 1 | `hosted-pilot-work-1-a1:gates` | `sha256:eb974a7f5ec1b337afeb736d5f5f55eb466edf8c0efbe67fec328b9db844faf1` |
| 2 | `hosted-pilot-work-1-a1:candidate` | `sha256:ffdf12321887e8e5c922d58c85b98ca72661efbbc60b2da9c32ddf3a2e324b7b` |

The attempt itself did not succeed: it exited 1 without changing the checkout,
and the deterministic gates recorded `rejected` with the reason
`infra: worker failed without changing anything`, parking the item. The owner
recorded a failure report:

| Fact | Observed value |
| --- | --- |
| Operation | `work.lease.report-outcome-v1` |
| Report | `outcome_2VRN93EEA817C55M1GZ56WF26T` |
| Outcome | `failed` |
| Disposition | `recorded` |
| Settlement effect | `lease-released` |
| `settled` | `false` |

The failure report is acknowledged and recorded, but it did **not** settle Work.
A subsequent lifecycle read observed the evidence tail at sequence 2, while the
`work.lease.read-v1` fact remained unknown with
`owner refused: runner-operation-denied (HTTP 403)`; that reader had no lease-read
scope. No successful Work settlement, terminal acceptance, or closure is claimed.

## Later systemd preflight

A separate systemd preflight, run after the Work #1 attempt, denied direct reads
of the runner credential. The sandboxed preflight could not read the credential
file by its ordinary path, so direct file access is not a usable credential
channel for worker or candidate code. The intended path remains the owner's
service credential handoff; this observation does not qualify credential use by
an unrelated host or principal.

This is a credential-read denial observation, not a full isolation claim against
arbitrary hostile code sharing the operator's user identity and not a statement
that the gateway or hosted deployment was qualified. It created no claim, lease,
run, or Work mutation.

## Owner facts and limits

- Release and Work settlement remain owner facts. This pilot observed one
  acknowledged lease acquisition and one recorded failure report; it does not
  establish successful settlement or a terminal Work decision.
- The pilot produced no deployed lane history. The lane event log used here is
  host-local recovery state under `LANECTL_STATE`, not a served, replicated, or
  durable-authoritative lane history.
- No served event stream, PostgreSQL owner migration, backup/restore, hosted
  deployment, or authority cutover was exercised.
- The systemd preflight denies direct runner-credential reads only. It does not
  grant work authority, and it does not substitute for owner-side lease and
  settlement checks.

References: [Vuoro coordination](../architecture/vuoro-coordination.md),
[full delivery stack](../full-stack-operation.md), and
[lane history boundaries](../architecture/lane-history-boundary.md).
