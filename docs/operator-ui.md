# Operator lifecycle views

The operator surfaces join Vuoro-owned work facts to local lane execution facts.
Work IDs and release IDs stay distinct. Every fact carries its source and
observation time; a successful outcome report remains pending until the owner
confirms `done` with resolution `accepted`.

Configure the owner connection as described in
[full-stack operation](full-stack-operation.md#vuoro-owner-and-served-state).
Read commands report unavailable coordination explicitly. They do not acquire a
lease or change work status.

## Inspect a lifecycle

Run these from the lanectl checkout, replacing the example identities:

```sh
uv run lanectl lifecycle --repo homelab-analytics --item freshness-fix --json
uv run lanectl verify --repo homelab-analytics --item freshness-fix
uv run lanectl tui --repo homelab-analytics --item freshness-fix --attempt freshness-fix-a1 --view active
```

The TUI also has Ready and Verification views, a plain table mode (`--plain`),
filtering, evidence inspection and source links. The selected release and attempt
remain selected during refresh. Evidence inspection shows gate results, checked
and landed commits, deployment expiry, owner evidence and owner acceptance.
Missing, rejected, stale and unknown evidence remain separate states.

## Preview and run

```sh
uv run lanectl claim-run --item freshness-fix --json
uv run lanectl claim-run --item freshness-fix --execute --expect sha256:PREVIEW_DIGEST
```

The default command only previews. The preview names the repository, work item,
release, lane and observed revisions. Execution rereads the owner and configuration
and refuses a changed preview before admission. It then uses the existing runner's
registration, lease, heartbeat and cancellation path. A refusal does not start a
worker; uncertain calls retain their existing exact-replay identity.

A release needs a matching `work = "homelab-analytics#123"` reference,
`work_complete = true`, and configured coordination to use claim-and-run. A digest
describes what was previewed; owner authority is checked again immediately before
effects.

## Hold a claim without starting a worker

For advanced inspection or handoff, use a reasoned claim-only hold:

```sh
uv run lanectl claim-hold --item freshness-fix --reason "Inspect before handoff" --json
uv run lanectl claim-hold --item freshness-fix --reason "Inspect before handoff" --execute --expect sha256:PREVIEW_DIGEST
uv run lanectl claim-hold --repo homelab-analytics --resume HOLD_ID --json
```

The hold uses the owner's finite lease expiry and displays its UTC deadline. It
starts no worker, sends no heartbeat and reports no work outcome. Recovery replays
only the recorded intent; it does not extend an acknowledged hold. A last-observed
receipt is not proof of current authority. The owner expires the hold under its
existing policy.

## Review and share a snapshot

```sh
uv run lanectl lifecycle-web --repo homelab-analytics --item freshness-fix --output /tmp/lane-review
uv run python -m http.server 8765 --bind 127.0.0.1 --directory /tmp/lane-review
```

Open the exported `/lifecycle/...` path on that server. The page includes linked
identities, evidence, attention reasons, accounting and the equivalent TUI jump.
`--base-url https://reviews.example.test` supplies a canonical HTTPS origin when
exporting into an existing static host. Exporting does not publish or host a site.

Each page is an observed snapshot, with source freshness shown explicitly. It
contains no external assets or scripts. Local-only evidence is labelled and stays
on the lane host; raw evidence bodies, runtime output and credential-bearing
references are excluded.

## Account for time and cost

```sh
uv run lanectl accounting --item freshness-fix
uv run lanectl accounting --item freshness-fix --attempt freshness-fix-a1 --json
```

Queue, execution, integration and verification intervals retain event timestamps
and checkpoints. Retry waits are separate from execution. Missing endpoints keep
the total unknown, with any known subtotal shown separately. Verification ends
only at a matching successful local receipt of confirmed closure.

Lane and operator usage retain units, the price revision and estimate labels.
Partly priced records preserve known token costs while leaving the full cost
unknown. Unattributed and unpriced usage remain visible; no usage is not zero cost.
Usage assigned to other work or excluded attempts is outside scope, rather than
unattributed. Coverage describes observed records only and stays unknown while an
unassigned pool remains.

Git source and frozen acceptance are cross-host-replicated. Served work state is
durable-authoritative. Exports and screenshots under `/tmp` are session-local.
