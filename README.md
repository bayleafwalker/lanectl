# lanectl

Autonomous implementation lanes. Cheap workers (OpenCode Go DeepSeek V4.1 Flash
first) implement planner-written WorkReleases in isolated worktrees; deterministic
gates decide preliminary acceptance; an integrator lands candidate trains.

Design and invariants: [ADR 0001](docs/adr/0001-autonomous-lanes.md).
Full delivery stack and activation: [operation guide](docs/full-stack-operation.md).
Planner cycle: [.claude/skills/lane-planner/SKILL.md](.claude/skills/lane-planner/SKILL.md).

```sh
lanectl doctor                         # is the estate healthy?
lanectl backlog list --open            # what is open, and in what state
lanectl backlog new <id> --repo R --title T --scope 'src/**'   # scaffold a draft release
lanectl backlog publish <id>           # lint and release it to the lanes
lanectl run --max 3                    # lanes implement ready releases
lanectl candidates && lanectl train <repo> && lanectl land <train_id>
lanectl deploy run <train_id>          # repos with [deploy]: dev deploy + health before land
lanectl deploy list | reap             # live dev deploys; tear down expired/landed/superseded
lanectl lanes | report | view --html out.html   # caps, precision and cost, management page
lanectl focus <id> [--role integrator]  # attribute this Claude session's usage to a release
lanectl tick                           # doctor + deploy reap + run (contrib/systemd timer)
lanectl otel export --out spans.json   # OTLP/JSON spans for an OTel collector
```

Run inside the checkout, or set `$LANECTL_HOME`.

Per-repo gate jobs (`[[repos.<r>.gate_jobs]]`) run in the attempt sandbox after acceptance;
dev deploys (`[repos.<r>.deploy]`) run on passed trains with a stripped environment. See
[stage 3 plan](docs/plans/2026-11-10-stage3-gate-jobs-and-train-deploys.md).

State: `$LANECTL_STATE` (default `~/.local/state/lanectl/events.jsonl`).
Governance and backlog: `$LANECTL_HOME` (a checkout of this repo's main).

`lanectl integrate` advances gate-accepted work only for the explicitly reviewed
`autonomous_classes` in `governance/integrator.toml`. With the default empty list,
`tick` remains worker-only. With classes enabled, a tick integrates before and
after execution: deterministic evaluation, train check, optional dev deploy,
local landing, then canonical GitHub PR publication where configured. Required
CI must pass for the exact PR head. Governance parks remain interactive; the
executor applies no fixes beyond the configured class and line budget.

Landing receipts now include the immutable `landed_sha` and `work_request`.
`train.built.checked_sha` binds successful checks to a commit. Failed or changed
trains cannot land. Older train records are rechecked rather than presumed valid.
`work.synced.pending_close` records a PR completion waiting for fresh canonical
ancestry proof; `noted` records a confirmed tracker note so retries can skip it.
`lanectl work reconcile` retries incomplete tracker effects without landing again.
An old receipt without a landed commit is reported as unknown, never inferred
from today's branch tip. A lost tracker-note acknowledgement may still produce
a duplicate note: tracker status convergence is idempotent, while note delivery
has no owner-provided idempotency key.

After an integrator fix, run `lanectl recheck <train_id>` to record a fresh check
bound to the updated commit, then redeploy that tip before landing where required.
Manual execution of the repository check alone does not update the proof receipt.

Configured Vuoro repositories require a complete Work release whose reference
names that repository. Native children and setup commands do not inherit the
configured coordination token environment variables. A lease guard covers native
execution, gates and immediate authorized integration; authority loss cancels the
process group and named sandbox service. Candidate acceptance does not settle
Work. Successful settlement is reported only after landing (and canonical PR
proof where configured), using the actual train check receipt; closure also
requires a fresh owner read reporting done/accepted. Awaiting verification remains
pending. `lanectl work reconcile` retries exact owner-journal completion after a
restart without substituting operator tracker status writes.

For a served event stream, autonomous effect execution additionally requires
`integrator_host` in the reviewed integrator policy to match this host's kernel
hostname. Other hosts may admit workers using atomic stream CAS but cannot deploy,
publish or land trains. Admission conflicts are recomputed before any worker
starts; external effects are reconciled from receipts instead of blindly replayed.
