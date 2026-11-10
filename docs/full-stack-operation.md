# Full delivery stack (0.2.0)

Lanectl now carries an intent through independently authored draft acceptance,
native implementation, deterministic gates, a checked train, disposable dev
deployment and landing. Optional Vuoro coordination supplies leases, evidence,
owner-confirmed completion and a served lane event stream. The operator still
owns policy, protected-path review and production promotion.

## Intent and maintenance intake

`lanectl spec --help` describes intent-file drafting. Select different author
and adversarial reviewer models; the acceptance author cannot implement its own
release, including after a routing change. Generated releases remain drafts.
`lanectl backlog publish ID` requires unchanged independent-review evidence and
reruns generated acceptance safely in the sandbox. Editing or rebasing a draft
invalidates its evidence and requires another review.

`lanectl closure scan --record` derives recurring planner/gate maintenance
proposals without inference. `lanectl closure draft --help` turns a proposal
into an independently reviewed, unpublished draft. These telemetry-derived
intents retain restricted data classification. Relevant evidence revisions
deduplicate intake; landed maintenance consumes its earlier evidence.

## Checks, deployment and canonical completion

The train's passing check and its dev deployment refer to an exact commit.
Failed trains, moved tips, changed worktree contents, expired deployments and
stale base commits cannot reuse a previous pass. After an integrator fix:

```sh
lanectl recheck TRAIN
lanectl deploy run TRAIN    # where the repository declares a deploy
lanectl land TRAIN
```

For repositories with `landing = "pr"`, a local landing does not close Work.
The integration executor publishes a stable train PR, waits for required CI,
merges the checked head, and independently verifies ancestry against freshly
observed canonical main. `lanectl work reconcile` retries pending tracker
effects without relanding. Lost tracker-note acknowledgements can still
duplicate notes because the existing note API has no idempotency key; terminal
status reconciliation converges independently.

## Unattended integration

`lanectl integrate` and the existing `tick` execute only task classes listed in
protected `governance/integrator.toml` `autonomous_classes`. The default remains
empty. The executor requires current evaluator acceptance, bounds fixes by
allowed class and aggregate lines, resumes existing trains, and rechecks
authority before effects. Served integration additionally requires the reviewed
`integrator_host` to match the designated machine; a host-local lock alone
does not establish distributed integration authority.

Ticks recover abandoned local attempts only after the recorded runner's host,
machine, boot and PID birth identity prove it is gone and its named sandbox is
inactive. Live runners, active orphaned sandboxes, foreign hosts and unknown
legacy identities are held. Recovered partial gates never become acceptance;
a new attempt reruns them. Worker namespaces mount control logs and recovery
journals read-only while retaining their own checkout for implementation.

Promote a class through a reviewed policy revision after examining real product
results. The ladder's week-long autonomous-operation and per-class product
evidence clocks are operational qualification, not claims supplied by the test
suite. Existing production-promotion decisions remain separate.

## Vuoro owner and served state

See [Vuoro coordination](architecture/vuoro-coordination.md) for protected
configuration, runner enrollment prerequisites, explicit owner migration,
hash-verified history import, authority cutover and backup requirements.

Configured Work releases claim before native execution and heartbeat during
it. Revoked, expired or uncertain leases cancel the native process group and
named systemd sandbox; a gate pass is never terminal Work acceptance. The runner
reports success only after checked landing/canonical merge and records closure
only after fresh owner facts show `done` and `accepted`. A report that remains
unsettled stays pending. Coordinated releases currently require one complete
Work outcome; partial releases are refused before dispatch rather than being
misreported as completed Work.

Local recovery journals are **host-persistent** and provide exact request
replay. A configured served stream is the **durable-authoritative** event home
only when its owner storage and backups are qualified. Stream writes use atomic
revision-checked batches. Lost replies replay the same request; conflicts require
a fresh decision. Served failures never silently select a second local log.

The optional Vuoro composition is source-supported. A hosted activation still
requires a released owner wheel, immutable service composition, Python 3.13,
migrated persistent storage, the gateway allowlist and separately authorized
production rollout. Source tests do not establish a deployed hosted runtime.

## Allocation and local inference

`admission_mode = "enforce"` on a reviewed allocation provider enables measured
capacity enforcement. The default is `shadow`. Enforcement requires fresh,
account/pool-scoped observations in matching units for verified applicable
fixed windows with known anchors. Host-only, stale, estimated and unknown
observations preserve static admission. A measured exhausted limit or active
denial blocks admission. Usage, denials and outstanding reservations are shared
across reviewed provider aliases of the same pool; every applicable model limit
also constrains admission. Reservations occur inside the admission transaction.

Protected `governance/routing.toml` may opt in `adaptive_classes` with
`max_relative_change`. Learning keeps the eligible model subset, needs the
minimum ruled evidence for every model, and stays within reviewed weight bounds.
Actual applied alternatives feed the deterministic dispatch record. Neither
allocation nor learning authorizes a new provider or changes data restrictions.

[The local provider](local-provider.md) offers an explicitly configured
`local/PROFILE` route using native OpenCode, a read-only provider configuration,
the existing exclusive inference lock and a redirect-refusing loopback relay.
Synthetic routing/isolation proofs establish transport behavior; restricted
product qualification and a routing-policy promotion remain separate evidence.
