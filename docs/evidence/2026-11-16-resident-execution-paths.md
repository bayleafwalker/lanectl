# Resident execution path source verification — 2026-11-16

## Scope

User-authorized extension of the resident-memory implementation: devbox native
OpenCode Go/DeepSeek V4.1 Flash, or on-demand workstation local inference with
execution isolated from the normal user. The source supports alternative
executor placements, not distributed concurrent ownership of one resident.

The native launcher, fixed model gateway, systemd bridge and opt-in NixOS module
are implemented. No host was accessed or activated. No provider/peer credential
was copied, inference subscription called, GPU model loaded, timer installed,
or qualification receipt fabricated during this work.

## Observed verification

```text
uv run pytest -q tests/resident
164 passed, 10 skipped in 24.55s
```

The ten skips are real AF_UNIX integration variants: this executor refuses
`socket(AF_UNIX, SOCK_STREAM)` with `EPERM`. Corresponding native relay protocol
tests run through a narrow TCP socket-factory fixture, while asserting the
exact configured Unix destination. The gateway listener contract is checked
separately. This is protocol evidence, not a real Unix transport qualification.

Coverage includes:

- Exact Go/local selection; no alternate endpoint/model/provider fallback.
- Immutable native config/executable hashes, cleaned environment and result
  identity; successful native fixture and refusal of invalid/uncertain results.
- Actual HTTP transport deadlines, redirect refusal, framing failure on partial
  or excessive streams, terminal SSE markers, header stripping and bounded input.
- SQLite reservation persistence across restarts and failures, clock rollback,
  local usage without an aggregate cap, and explicit connection closure.
- Protected systemd arguments, descriptor-relative HOME handoff, namespace and
  capability configuration, cleanup proof, source recheck and generation fencing.
- Unknown cleanup retains the slot and stores only a diagnostic checkpoint;
  worker result/artifact capture waits until recovery proves cleanup.

The Go/local configuration examples render and pass their pure schema checks.
`systemd-analyze 257 verify` accepted the generated tool property syntax using
a harmless executable, including private network, explicit binds and
`PrivateTmp=disconnected`. No real unit was launched by that syntax check.

## Remaining gates

The full repository suite is still a required host/CI gate. Its previously
reproduced systemd-user-bus failures in this cloud executor remain failures;
no existing test, sandbox or acceptance gate was weakened. See the PR's final
full-suite result for the complete run against this source revision:

```text
uv run pytest -q
70 failed, 1311 passed, 10 skipped in 197.60s
```

Nix evaluation/build is unavailable here. On the target, require the host
repository's `nix flake check`, builds/dry runs, exact interpreter/package
imports, socket activation/permissions, mount and namespace negative probes,
native OpenCode/model/tool round trips, cgroup cancellation/recovery, disk quota,
and the peer's own credential/source grant. Synthetic `/healthz` and model
catalog responses do not establish readiness.

Native OpenCode's standalone mode was checked against official v2.2.3 source:
it uses an ephemeral private HTTP server. That concrete compatibility finding
led to `PrivateNetwork` plus one fixed filesystem model socket, rather than
allowing access to arbitrary host-loopback services. Exact native binary
behavior still needs target qualification.

References: [native execution](../resident-native.md),
[host installation and rollback](../../contrib/resident/nixos/README.md),
[existing episode evidence](2026-11-16-resident-episodes.md),
[official standalone source](https://github.com/anomalyco/opencode/blob/v2.2.3/packages/cli/src/services/standalone.ts).
