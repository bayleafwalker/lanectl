# 2889 — Fenced train backend for ownership-guarded repositories

Status: implementation and qualification in progress (2026-11-13). Client source
is released as 0.2.6; the dedicated host account and first service generation are
installed. The stricter filesystem allow-list correction remains under review
and must be applied and requalified before Sovite's policy changes. This document
records the approved design; current evidence is linked from `docs/fenced-train.md`.

## Problem and security boundary

`environment` isolation preserves host ownership IDs, which is why Sovite is
currently allowed to use it.  It does not stop arbitrary train code running as
the operator from opening the operator's files.  In particular, the train must
be unable to read or modify same-user material below `~/.config`, `~/.local`,
`.ssh`, and runtime credential directories; Forgejo tokens/CLI keys; runner
credentials; or any checkout other than its own.  Clearing environment
variables is necessary but does not satisfy this boundary.

The fence is not a defence against a host administrator, kernel compromise, or
network service which deliberately hands a credential to untrusted code.  The
network policy remains exactly the policy of the current train: the backend
must neither silently add access nor make an unreviewed network-policy change.

It must allow the train worktree read/write, the Nix store read-only, the
approved toolchain/runtime inputs, and the existing network behaviour.  Its
ownership view must also be compatible with Sovite: root-owned ancestors and
`/nix` must retain their host ownership IDs as observed by Sovite's checks.

The existing evidence is decisive for the compatibility requirement: on Sovite
main `00d29faa`, the normal run passed 2,797 tests and skipped 1,140, while the
user-namespace execution had 66 failures and 25 setup errors because trusted
root-owned ancestors appeared as UID 65534.  There is no fallback from a
fenced backend to `environment`; a launch failure fails the train.

## Candidates

| Mechanism | Sovite ownership compatibility | Credential/other-repo denial | Host privilege/configuration | Operating cost |
| --- | --- | --- | --- | --- |
| `bwrap` user namespace, selective RO binds | No: a bind of real `/nix` remains unmapped; synthetic `/` is mapped to the caller. | Strong filesystem allow-list when only the worktree, `/nix`, devices/proc/tmp, and explicit runtime inputs are mounted. | No privilege for the probe. | Maintain a complete input/mount manifest; caches and DNS/CA inputs need deliberate mounts. |
| Unprivileged user namespace plus idmapped mounts | Potentially, but only if every ownership-sensitive bind is idmapped to preserve the host IDs.  Not established here. | Strong with an allow-list mount namespace. | Kernel support plus `mount_setattr(MOUNT_ATTR_IDMAP)` and permission to create the idmapped mounts; usually a privileged launcher or carefully configured helper. | High: per-mount ID maps, lifecycle cleanup, and filesystem/kernel support matrix. |
| `systemd-run --user` with `InaccessiblePaths=`, `ProtectHome=`, `TemporaryFileSystem=` | Yes: no user-ID remapping, so it retains host ownership IDs. | Path deny-list is defence in depth, not a complete same-UID boundary unless combined with a mount allow-list; omissions and alternate paths remain risks. | User manager and mount-namespace delegation must be available. | Low/moderate, but needs a comprehensive policy and negative tests. |
| Separate static system user, launched by a root-owned systemd service (or `DynamicUser` plus privileged mounts) | Yes: no user namespace is needed. | Strong: distinct UID plus mount allow-list prevents access to the operator home and other repos. | Yes: account/service/authorization and a privileged worktree-mount or ACL setup. | Moderate; durable service hardening and cleanup are operational work. |
| Landlock | Yes: it does not change UID presentation. | Can deny read/write for credential and other-repo hierarchies, but is an in-process, one-way policy and cannot grant access beyond normal DAC; it is weaker than a mount allow-list against policy omissions. | No privilege when ABI/ruleset support is present. | Moderate: syscall rule builder, ABI compatibility and careful inherited-FD policy. |

`systemd-run --user` is useful to retain ownership but is not, by itself, the
requested fence.  `InaccessiblePaths` can make named credential paths
unreachable; it cannot reliably express “all same-user secrets and every other
repository” without an allow-list filesystem.  Landlock is a useful additional
layer, not the qualification choice on its own.

## Read-only host feasibility probes

All probes below were bounded and made no persistent system changes.  No
credential content was read: credential probes used `open(2)` only, closed an
opened descriptor immediately, and reported only errno.  The runtime’s own
mount namespace already presents `/` and `/nix` as UID 65534, so these results
cannot certify their *host* IDs; the comparison is their presentation under
each candidate.

| Probe | Result | Interpretation |
| --- | --- | --- |
| `bwrap 0.12.0 --unshare-user --uid 1000 --gid 100` with RO `/nix`, RW current worktree, tmpfs home/tmp, and no `/projects` bind | `open(~/.config/forgejo/workstation-scope-token)` → `ENOENT` for read and write; `/projects/dev/sovite` → `ENOENT` for read and write. Synthetic `/` and worktree appeared UID 1000; real bound `/nix` remained UID 65534. | The allow-list does deny the target classes, but the unmapped Nix ownership reproduces the known incompatibility.  Not qualified for Sovite. |
| `unshare --user --map-root-user` | Process became UID 0; `/` and `/nix` remained UID 65534 while the worktree appeared UID 0. | Confirms ordinary unprivileged user namespaces do not solve the ownership view. |
| `systemd-run --user` (including `ProtectHome=tmpfs`) | Failed before execution: user bus transport returned `Operation not permitted`, even with `XDG_RUNTIME_DIR=/run/user/1000`. | This executor cannot qualify user-manager properties.  It is not evidence of a host-wide unsupported feature. |
| Landlock version syscall | ABI 7 reported. | The kernel exposes Landlock; no ruleset was installed, so no policy was changed. |
| Idmapped mounts | Not attempted. | A safe meaningful attempt needs a mount helper or privileged mount setup; the ordinary user-namespace probe above is not an idmapped-mount test. |

The bubblewrap result agrees with the earlier feasibility observation: mapping
synthetic root/tmp to the current UID does not remap a real bound `/nix`.

## Recommendation

Do not replace Sovite's explicit `environment` exception yet.  Qualify a
**privileged, separate-UID fenced backend**: a root-owned systemd system service
starts each train as a dedicated static `lanectl-train` account, creates a
per-train checkout accessible only to that account, and gives it an explicit
mount allow-list (worktree RW; `/nix` RO; required CA/DNS/device/proc/tmp and
toolchain inputs only).  Keep the current stripped environment and add Landlock
as defence in depth if the implementation can do so before executing any
candidate-controlled program.

This preserves the host's root ownership presentation because it does not use
a user namespace, while DAC plus the mount allow-list denies the operator's
home and unrelated repositories.  A static account is preferred to bare
`DynamicUser`: it makes ownership and reusable build-cache policy explicit.
`DynamicUser` is acceptable only if the privileged launcher supplies equivalent
per-train writable mounts and no shared state.

Required operator change before implementation/qualification:

1. Create a non-login `lanectl-train` system user/group.
2. Install a root-owned systemd **system** service/template and root-owned
   launcher that accepts only a train ID and an already-created, validated
   worktree path (never arbitrary mount/property arguments).
3. Authorize the lanectl coordinator to start only that template, and arrange
   per-train worktree ownership/ACL for `lanectl-train`; the coordinator itself
   must not receive general sudo.
4. Configure the service with a filesystem allow-list and deny-by-default home
   and project roots, bind `/nix` read-only, keep today's network namespace and
   policy, and ensure cleanup on success, failure, and cancellation.

That is a host-privilege/configuration change.  Without it, there is no
qualified candidate from these probes that both preserves Sovite ownership
checks and provides the requested same-user credential boundary.

## Qualification acceptance tests

Implementation may be considered only after all of the following pass on the
operator host using Sovite main `00d29faa` and the production-style launcher:

1. Full Sovite suite parity: the fenced run has the normal baseline outcome
   (2,797 passed / 1,140 skipped at the recorded baseline, subject only to a
   reviewed upstream baseline update), with no ownership-guard failures.
2. Negative filesystem probes attempt read and write opens, reporting errno
   only, for representative paths under `~/.config`, `.local`, `.ssh`, runtime
   credentials, Forgejo token/CLI-key locations, runner credential locations,
   and a separate repository.  All must fail; the worktree write probe must
   succeed.  Tests must not read secret bytes.
3. The train can read `/nix` and required toolchains, and network behaviour is
   unchanged from today.  A harness test asserts the exact mount/input
   allow-list and fails closed for missing required inputs.
4. Integration tests prove a launcher or fence setup failure records a failed
   train and cannot select or fall back to `environment`.  Coordinated
   admission/execution must continue refusing unfenced trains.
5. Regression tests run the same probes through setup, check, recheck, and
   historical land paths, including cancellation/cleanup, so no alternate train
   command bypasses the backend.

If the operator declines the required system service/account authorization, the
correct disposition is `DISPATCH_OUTCOME: ESCALATED`: the choice is between
retaining Sovite's explicitly unsafe environment-only exception and granting
the host capability needed for a real fence; it is not an implementation choice
lanectl can safely make on its own.
