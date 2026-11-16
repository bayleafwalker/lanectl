# Resident episode commissioning

`lanectl resident` executes one bounded episode of a logical resident. It does
not implement a persistent native Goal, select an agenda, schedule itself,
publish external effects, close Sprintctl items, or enter the WorkRelease
acceptance/landing state machine. The existing execution owner may invoke it
from its timer, completion notification or admitted work path.

## Ownership and defaults

Start with `contrib/resident/profile.example.json`. It is deliberately disabled
and contains no executable, credential, endpoint or qualification claim. Choose
a real isolated workspace and a separate protected state root. One resident
identity and coordination root are bound to a workspace in the existing local
event log. All invocations must use that same selected log authority on one
protected host. This pilot accepts only the local durable `EventLog`;
`run`, `status`, `fence` and `recover` reject remote or buffered backends.
`open_log()` continues to refuse a local fallback when a served backend is
configured. Do not remove a served-backend marker or override an existing
authority to bypass this refusal.

Remote event append buffering and a host-local lock are insufficient to make
external execution atomic with distributed admission and fencing. Supporting
that mode requires an owner-level admission protocol and independent
qualification. The pilot's local episode receipt log does not replace
Sprintctl's work authority or provide a local Sprintctl fallback.

The resident process cannot own its profile, qualification receipts, control
log, lock files or checkpoint objects. Profiles and qualification/source-check
receipts must be root-owned with protected parent paths. Root-owned NixOS links
into the immutable store are supported. State and workspace must be disjoint.
Use a separate launcher/tool identity and enforce the boundary on the host.

**This module does not supply an OS sandbox or provider credential isolation.**
It clears inherited environment credentials and bounds a process group, but
those mechanics alone do not prevent reading an authentication cache, escaping
with `setsid`, contacting an unrestricted endpoint, or exceeding a host-wide
budget. The qualified launcher must enforce those properties. Existing native
subscription credentials must not be copied into the resident workspace.

The fixture tests run a real credential-free child under an emulated
configuration-ownership probe. They establish the episode protocol and process
behavior, not qualification of a native model route or a deployed host.

## Qualify one route

An enabled profile adds an explicit execution block:

```json
{
  "enabled": true,
  "route": "reviewed-native-route",
  "argv": ["/nix/store/ACTUAL-PIN/bin/resident-native-launcher"],
  "timeout_s": 2700,
  "executable_sha256": "ACTUAL_64_CHARACTER_SHA256",
  "qualification_file": "/etc/lanectl/resident-route-qualification.json",
  "qualification_sha256": "ACTUAL_64_CHARACTER_SHA256"
}
```

These placeholders are not valid executable configuration. Use an immutable
launcher with no inline credentials in its arguments. The launcher may compose
the existing AgentOps/native adapters and the approved memory tools; it must
not add an independent scheduler. The maximum episode wall time is 2,700
seconds. A fresh isolated HOME is supplied, but it is not the credential
boundary.

Prepare the protected candidate profile, then inspect:

```sh
lanectl resident describe --profile /etc/lanectl/resident.json
```

The description returns a `recipe_sha256`. It binds the complete profile except
the qualification file path/digest, avoiding a circular digest. After actual
host/route probes, the protected commissioning owner issues a receipt:

```json
{
  "schema": "lanectl.resident-qualification/v1",
  "recipe_sha256": "ACTUAL_RECIPE_DIGEST",
  "valid_until": "ACTUAL_FUTURE_UTC_TIMESTAMP",
  "provider_credentials_isolated": true,
  "execution_boundary_enforced": true,
  "budget_enforced": true,
  "source_recheck_enforced": true
}
```

Record those booleans only after observing the actual boundary. This command
does not create a qualification receipt or infer qualification from the
profile. The receipt's exact file SHA-256 goes into the profile. Qualify the
launcher against the declared profile, native runtime/model configuration,
process-tree cleanup, credential visibility, egress, hard resource/inference
limits and admission-time source recheck. Future effect admission still checks
its own current source and authorization basis.

Keep the profile disabled while any required qualification is missing. A
changed command, workspace, scope, timeout or policy changes the recipe digest
and requires a matching new receipt. Qualification expiry is checked at every
new episode; a duplicate wake only returns its existing receipt.

## Context and per-episode source check

AgentOps owns context construction. The input must be a `resident-context/v1`
packet whose status is `ready`, whose `authorizes_effects` is `false`, and whose
resident scope matches the profile. Set `context_scope` to bind project and
branch as in the example. Blocked context does not launch a process.

The runner verifies both hashes:

* `--context-sha256` is the SHA-256 of the exact file bytes.
* The packet's `digest` is the SHA-256 of canonical JSON excluding the `digest`
  field: sorted keys, compact separators, UTF-8, no NaN and no trailing newline.

It also checks the exact v1 envelope, mandatory section identities/content,
ordered unique sections, source-reference union, memory/worker scope,
omissions, declared serialized byte budget and the runner's 256 KiB input
ceiling. Token measurement metadata must match the emitted schema; the runner
does not independently reproduce the caller's tokenizer count. These integrity
checks do not establish currentness.

`require_source_recheck` defaults to true. The protected source owner rechecks
the packet and supplies this admission receipt:

```json
{
  "schema": "resident-context-recheck/v1",
  "context_digest": "ACTUAL_PACKET_INTERNAL_DIGEST",
  "context_sha256": "ACTUAL_PACKET_FILE_SHA256",
  "generation": 1,
  "status": "unchanged",
  "authorizes_effects": false,
  "checked_at": "ACTUAL_UTC_TIMESTAMP",
  "valid_until": "ACTUAL_UTC_TIMESTAMP_WITHIN_60_SECONDS"
}
```

The runner requires `checked_at <= now <= valid_until` and a positive validity
span no longer than 60 seconds. It checks freshness again immediately before
releasing the child exec gate. A source check remains an observation at a
moment, not permission to use stale sources for subsequent effects. A profile
may explicitly set `require_source_recheck:false` only when its qualified
launcher performs the admission check itself; route qualification must still
declare and substantiate `source_recheck_enforced:true`.

## One bounded wake

Use the current generation from `status`, an owner-issued wake ID and the exact
packet/receipt hashes:

```sh
lanectl resident status --profile /etc/lanectl/resident.json
lanectl resident run \
  --profile /etc/lanectl/resident.json \
  --wake-id owner-event-0001 --generation 1 --work-ref stories#1 \
  --context /var/lib/agentops/context/ACTUAL_DIGEST.json \
  --context-sha256 ACTUAL_FILE_SHA256 \
  --source-recheck /run/agentops/resident-recheck.json \
  --source-recheck-sha256 ACTUAL_RECEIPT_FILE_SHA256
```

This is a oneshot interface suitable for the existing protected systemd
admission path. Do not install another resident polling loop. The host service
should add its own wall-time and cgroup limits and preserve the selected event
backend. No timer or enabled unit is included here.

The response is JSON `lanectl.resident-receipt/v1`. CLI exit 0 means a normal
completed/stopped receipt or successful inspection; 3 means busy/refused,
interrupted, failed or uncertain work; 2 means invalid input or another reported
operation error. Inspect the JSON status and outcome, not only the exit code.

The coordinator holds a nonblocking workspace lock for the whole episode. A
duplicate wake ID with the same profile, generation, work reference and context
returns the original episode receipt without rerunning work. A changed basis
under the same ID is rejected. A different wake arriving while busy gets a
durable busy receipt; it is not silently queued. The owning work/trigger path
decides whether to admit a new wake later.

Before invoking the native launcher, the runner stores the exact context bytes
and a durable start event containing coordinator and child kernel birth
identities. A gate wrapper cannot exec the launcher until that transaction
completes. A separate final event-log critical section checks the generation
and source-receipt expiry before releasing the gate; fencing uses the same
lock. A coordinator crash before admission closes the gate without running
the task.

## Native launcher result contract

The exact context packet is provided on stdin. The clean environment includes:

* `LANECTL_RESIDENT_EPISODE`
* `LANECTL_RESIDENT_GENERATION`
* `LANECTL_RESIDENT_CONTEXT_SHA256`
* `LANECTL_RESIDENT_RESULT`, the assigned result file within the workspace
* a fresh `HOME`, fixed minimal `PATH`, and locale settings

No parent API keys, credential directory, provider overrides, proxy variables
or `PYTHONPATH` are inherited. The qualified launcher must add only the approved
runtime configuration through its protected route.

Write this JSON to the assigned result file, preferably by atomic replacement:

```json
{
  "schema": "lanectl.resident-result/v1",
  "episode_id": "ACTUAL_EPISODE_ID",
  "generation": 1,
  "stop_reason": "completed",
  "artifacts": ["drafts/story.md", "canon/setting.md"],
  "continuation": {
    "next_action": "Ask the critic whether the witness is credible",
    "open_questions": ["The priest's involvement remains an allegation"]
  }
}
```

Other worker stop reasons are `idle`, `waiting_for_worker`, `budget_exhausted`,
`context_unavailable`, `execution_uncertain`, `repeated_failure`,
`model_unavailable` and `outside_scope`. Result identity and generation must
match. A nonzero process exit cannot be hidden by a successful-looking result.
`completed` means the episode returned its result contract successfully; it is
not Sprintctl completion, editorial acceptance or external-effect success.

Artifact paths must be safe relative paths within the profile's declared
roots. Every path component is opened without following symlinks. The runner
copies actual bytes into immutable content-addressed checkpoint objects, with
file SHA-256 and size. Objects are staged and fsynced before atomic no-clobber
publication; a crash cannot leave partial bytes under the final digest name.
Limits are 128 declared artifacts, 16 MiB of captured
artifact content and a 64 KiB result file. Continuation is evidence supplied by
the worker, never an authority grant.

When a result is missing or invalid, the checkpoint attempts a bounded,
symlink-refusing walk of the declared artifact roots to preserve partial work.
Any incomplete capture is recorded explicitly; the workspace itself remains
part of the backup/recovery manifest. Partial snapshots never change an
interrupted or failed episode into completion.

Stdout/stderr remain local diagnostic logs, not automatically retained memory.
A 2 MiB combined-output watchdog interrupts noisy children. Host filesystem and
cgroup limits remain necessary: a polling watchdog is not a hard disk quota.

## Continuation, fencing and recovery

AgentOps consumes the checkpoint's continuation, exact artifacts and source
basis when building the next context packet. Sprintctl remains the work owner.
The next episode uses a new wake ID and the current generation; there is no
automatic recursive launch from a worker result.

```sh
lanectl resident fence --profile /etc/lanectl/resident.json \
  --generation 1 --reason 'activate a separately qualified runtime generation'
lanectl resident recover --profile /etc/lanectl/resident.json --generation 2
```

Fencing advances exactly one generation. Active work observes the fence,
terminates its owned process group, and cannot report current-generation
completion. The workspace lock remains held until cleanup and checkpointing.
Old artifact bytes may be preserved for review but are not automatically
integrated into a successor task.

Unresolved cleanup remains `unknown` even if a fence advances the generation;
it never frees the active slot. Cleanup refuses to signal a process whose
observed kernel birth identity differs from the recorded child. This guard
does not replace the host's process-tree/cgroup boundary.

Recovery refuses a live coordinator, foreign machine, unreadable birth
identity or unresolved child process. For proven local abandonment it stops
the recorded process group, checks that it is inactive, advances the generation
and writes an interrupted checkpoint. It never upgrades a worker's last prose
to accepted work. A successful launcher is also prevented from leaving ordinary
background children behind; the qualified host boundary must contain children
that deliberately change session/cgroup identity.

Keep the event log, protected checkpoint object tree and workspace in the same
recovery manifest. Restore them with the matching profile/runtime generation,
then reconcile uncertain work before admitting another episode. Do not erase
receipt history or silently select a new local log to clear a refusal.

## Validation and commissioning gates

Run `uv run pytest -q` before committing. Focused tests are in
`tests/resident/test_resident.py`; they include real timeout, killed-coordinator
recovery, duplicate wakes, generation fencing, gated launch, context integrity,
source-check freshness, crash-safe object publication, unresolved cleanup,
observed PID reuse, unsupported-backend refusal, symlink/path refusal and
credential environment checks. See the dated evidence note for the current
unmet full-suite host gate; a focused pass is not a substitute for that gate.

Before enabling an actual profile, additionally prove native tool availability,
tool-process credential/cache isolation, direct API/database denial, egress and
IPv6 policy, aggregate provider limits, process-tree containment, source-owner
currentness checks, backup/restore and exact loaded runtime/profile identity.
None of those host qualifications is asserted by adding these source files.
