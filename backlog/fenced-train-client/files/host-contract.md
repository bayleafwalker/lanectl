# lanectl fenced train backend (workstation)

Source: `modules/system/lanectl-train-fence.nix`, launcher
`modules/system/lanectl-train/launcher.py`, enabled in `hosts/workstation`
with `profiles.lanectlTrainFence.coordinatorUser = "bayleaf"`. Design and
qualification gate: lanectl `docs/design/2889-fenced-train-backend.md`
(operator approval 2026-11-11).

A train runs a repository's setup/check commands against a candidate worktree.
Here it runs as the static `lanectl-train` account (uid/gid 1120, nologin,
home `/var/empty`) inside a root-owned systemd system unit, so train code
cannot open the coordinator's same-user credentials or other checkouts. There
is no user namespace and no ID remapping: `/`, `/var`, `/var/lib`, `/nix` and
the spool ancestors appear root-owned to the train, as Sovite's ownership
checks need.

## Interface lanectl implements

All paths are fixed. The caller controls only the train id and the contents
of its own train directory; there are no mount, property or path arguments.

| Item | Value |
| --- | --- |
| Train id | `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$` (no dots, no slashes) |
| Spool | `/var/lib/lanectl-train/trains` (owner `bayleaf`, mode 0700) |
| Train dir | `/var/lib/lanectl-train/trains/<id>/` |
| Request | `<train dir>/.lanectl-train/request.json` |
| Result | `<train dir>/.lanectl-train/result.json` |
| Authoritative receipt | `/var/lib/lanectl-train/results/<id>.json` (root-owned, coordinator read-only) |
| Unit | `lanectl-train@<id>.service` |
| Logs | journal: `journalctl -u lanectl-train@<id>.service -o cat` (stdout/stderr of the train plus `lanectl-train:` launcher lines) |

### Lifecycle

1. As the coordinator, create `<train dir>` and put a **self-contained**
   checkout in it (e.g. `git clone --no-hardlinks`, or a copy). A `git worktree`
   whose `.git` points under `/projects` will not work: `/projects` is not
   visible to the train. The dir must be owned by the coordinator and must
   exist before the unit starts.
2. Write `.lanectl-train/request.json`.
3. Start: `systemctl start --no-block lanectl-train@<id>.service`
   (authorized by polkit for the coordinator only; no sudo).
4. Prepare (root, before any train code): validates the id, the dir (no
   symlink in PID 1's host-root view, coordinator-owned), the request, and refuses hardlinked files or
   device nodes anywhere in the tree (chowning a hardlink would change the
   file outside the dir). It deletes any stale `result.json`, then chowns the
   tree to `lanectl-train` and sets the top dir to 0700. While the train runs,
   the coordinator cannot read or write the dir.
5. Run (as `lanectl-train`, sandboxed): executes `argv` with `cwd`, stdin
   `/dev/null`, and only this environment: `HOME=<train dir>/.lanectl-train/home`,
   `TMPDIR=/tmp` (private), `PATH=/run/current-system/sw/bin`, `LANG=C.UTF-8`,
   `SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt`, `LANECTL_TRAIN_ID`,
   `LANECTL_TRAIN_DIR`, then the request's `env` entries (which may override any
   of these). Nothing is inherited from the coordinator.
6. Finish (root, after systemd has killed the whole control group): chowns the
   tree back to the coordinator (directories get `u+rwx` so the coordinator can
   delete them), writes `result.json` with the coordinator's credentials, and
   then publishes the root receipt with `handed_back = true` and clears
   `/run/lanectl-train/<id>`. Handback errors publish a failed receipt with
   `handed_back = false`, requiring operator recovery.
7. The coordinator waits for the root-owned receipt and the unit to be inactive
   (`systemctl show -p ActiveState --value lanectl-train@<id>.service` is exactly
   `inactive` or `failed`), reads
   the receipt and removes the train dir when done. Failed instances are
   garbage-collected (`CollectMode=inactive-or-failed`); the root-owned receipt
   is the outcome record, not `systemctl status` or the in-tree convenience copy.
   The client must verify root ownership, regular-file type, non-writable mode,
   matching train ID, `handed_back = true`, and matching `request_sha256` (SHA-256 of the exact request
   file bytes). A missing, untrusted or mismatched receipt fails the command.
   The root prepare step removes an earlier receipt before execution. Use a
   fresh ID for each command, never reinterpret an earlier result as a new run.

Cancel: `systemctl stop lanectl-train@<id>.service` (kills the control group,
including processes that called `setsid`; finish still runs). Status while
running: `systemctl show -p ActiveState,SubState,MainPID lanectl-train@<id>.service`.
`systemctl reset-failed lanectl-train@<id>.service` is also allowed. Clients must
use a fresh ID and a fresh request nonce for every command. A deliberate manual
same-ID rerun requires confirmed terminal state and a new nonce, never old bytes.
Nonzero `is-active` is insufficient: activating/deactivating are not terminal.

Prepare and finish have explicit 600-second limits for large dependency trees.
The same stop limit permits a signal-ignoring process up to 600 seconds before
systemd escalates to SIGKILL. A client must allow ownership handback to finish;
an interrupted handback may require operator recovery as described below.

### request.json (version 1)

```json
{
  "version": 1,
  "argv": ["/run/current-system/sw/bin/bash", "-lc", "make check"],
  "cwd": "repo",
  "env": {"CI": "1"},
  "timeout_sec": 3600,
  "nonce": "0123456789abcdef0123456789abcdef"
}
```

- `version`: must be `1`. Unknown fields are rejected.
- `argv`: non-empty list of strings; `argv[0]` resolved via the run `PATH`
  unless absolute.
- `cwd`: optional, relative to the train dir, no `..` components (default `.`).
- `env`: optional object, names `^[A-Za-z_][A-Za-z0-9_]{0,127}$`, string values.
- `timeout_sec`: integer `1..21600` (`maxTimeoutSec`). systemd's
  `RuntimeMaxSec` is fixed at `maxTimeoutSec + 120` as the root-enforced cap.
- Max file size 256 KiB.
- `nonce`: required fresh 32-character lowercase hexadecimal value; generate
  it per submission (for example, Python `secrets.token_hex(16)`). The digest
  covers it, preventing stale receipt reuse even when other fields match.

The root prepare step writes the validated copy to
`.lanectl-train/request.validated.json`; the run step reads only that copy.

### result.json (version 1)

```json
{
  "version": 1,
  "train_id": "t1",
  "outcome": "succeeded",
  "service_result": "success",
  "exit_code": "exited",
  "exit_status": "0",
  "error": null,
  "request_sha256": "sha256:SHA256_OF_EXACT_REQUEST_BYTES",
  "handed_back": true,
  "started_at": "2026-11-11T20:00:00+00:00",
  "finished_at": "2026-11-11T20:10:00+00:00",
  "elapsed_sec": 600.123
}
```

`outcome` is one of:

| outcome | meaning |
| --- | --- |
| `succeeded` | command exited 0 |
| `failed` | command exited non-zero (see `exit_status`) or died otherwise |
| `timeout` | `timeout_sec` elapsed (launcher exit 124 after the deadline) or the systemd hard cap fired |
| `cancelled` | supervisor killed; this includes an operator stop and train-originated signals |
| `rejected` | prepare refused the train; `error` says why; no train code ran |

`service_result`, `exit_code` and `exit_status` are systemd's
`$SERVICE_RESULT`, `$EXIT_CODE`, `$EXIT_STATUS` for the unit. A result is not
an integrity claim against the train itself (train code chooses its own exit
status). The separate root-owned receipt records systemd's observed exit and
prepare rejection. Timeout/cancel labels do not prove the termination initiator:
the per-request supervisor shares the train UID and can be signalled by train
code. Only systemd's global `RuntimeMaxSec` cap is independently root-enforced;
the coordinator also bounds its wait and stops the exact unit.
Candidate code can forge or symlink its in-tree
copy; clients must not use that copy to decide success. Root publishes its
receipt even if the hostile control directory prevents the convenience copy.

If the train dir is missing or is not a coordinator-owned directory at start,
no in-tree result can be written; the root receipt records rejection without a
successful handback and the unit fails. The reason is also in the journal.
lanectl must treat a failed start or a missing result after the unit is
inactive as a failed train and must never fall back to `environment`
isolation.

## What the sandbox allows and denies

- Read-write: only `/var/lib/lanectl-train/trains/<id>` (bind), plus a private
  `/tmp` and `/var/tmp`.
- Root-only writes: `/var/lib/lanectl-train/results` is separately bound for
  the privileged post-step. Its root ownership and mode 0755 deny train and
  coordinator writes; they can read the receipt metadata. It contains no
  request bodies, environment or command output.
- Read-only: the rest of the host tree (`ProtectSystem=strict`), including
  `/nix`, `/etc` (CA bundle, `resolv.conf`), `/run/current-system`, and the
  nix-daemon socket (`/nix/var/nix/daemon-socket`).
- Hidden: `/home`, `/root`, `/run/user` (`ProtectHome=yes`); all of `/var/lib`
  (tmpfs, so sops-nix's age key, `/var/lib/cryptsetup-keys`, docker,
  NetworkManager, other trains; except the own train and root receipt binds);
  `/projects`, `/projects-snapshots`, `/media`,
  `/mnt`, `/games`, `/srv`, `/boot`, `/var/spool`, `/var/db`, `/run/secrets*`,
  `/run/secrets-for-users*`, `/run/lanectl-train`, `/run/docker.sock`,
  `/run/libvirt`, `/run/nordvpn`, SSH host keys.
- Other users' processes are invisible (`ProtectProc=invisible`).
- No capabilities, `NoNewPrivileges`, no SUID/SGID creation, private devices,
  kernel tunables/modules/logs/cgroups/clock/hostname protected, native
  syscall ABI only, private keyring, SysV IPC removed at stop.
- Network: unchanged (no network namespace or address filtering), matching
  today's trains. User namespaces inside the train are not restricted either
  (`RestrictNamespaces` unset), so rootless tooling behaves as today, subject
  to `lanectl-train` having no subuid/subgid ranges.

## Operator apply

Preconditions: this branch merged; the coordinator's home stays mode 0700
(asserted at evaluation: `users.users.bayleaf.homeMode`).

```bash
cd /projects/dev/gitops-nixos
nix flake check
sudo nixos-rebuild switch --flake .#workstation
```

Expected: `getent passwd lanectl-train` shows uid 1120 with a nologin shell;
`stat -c '%a %U' /var/lib/lanectl-train/trains` prints `700 bayleaf`;
`systemctl cat lanectl-train@x.service` shows the unit. Smoke test as
bayleaf, no sudo:

```bash
d=/var/lib/lanectl-train/trains/smoke
mkdir -p $d/.lanectl-train
printf '%s' '{"version":1,"argv":["sh","-c","id -u; test ! -r /home/bayleaf/.ssh; touch ok"],"timeout_sec":60,"nonce":"0123456789abcdef0123456789abcdef"}' > $d/.lanectl-train/request.json
systemctl start --no-block lanectl-train@smoke.service
sleep 3; cat /var/lib/lanectl-train/results/smoke.json   # outcome "succeeded"
journalctl -u lanectl-train@smoke.service -o cat | tail
rm -rf $d
```

The Sovite parity run and the remaining lanectl qualification tests (design
doc, "Qualification acceptance tests" 1-5) are the gate before lanectl
switches Sovite off its `environment` exception.

## Rollback

Set `profiles.lanectlTrainFence.enable = false;` in
`hosts/workstation/default.nix` (or revert the commit) and switch:

```bash
cd /projects/dev/gitops-nixos
sudo nixos-rebuild switch --flake .#workstation
```

or boot the previous generation. The account, unit and polkit rule disappear.
Left on disk: `/var/lib/lanectl-train` (remove with
`sudo rm -rf /var/lib/lanectl-train` after checking no train dir is still
owned by uid 1120). A train interrupted by the switch is killed with its unit;
if finish did not run, its dir may still be owned by uid 1120: fix with
`sudo chown -R bayleaf:users /var/lib/lanectl-train/trains/<id>`.

## Residual risks

- Network egress is open, as today: train code can reach any network service,
  including localhost services that authenticate by source address only, and
  can exfiltrate whatever is in its own dir.
- The fence is a deny-list over a read-only host tree, plus DAC. World-readable
  files outside the hidden paths stay readable (e.g. `/etc`, `/nix/store`,
  which may hold secrets copied into the store by mistake, world-readable
  files under `/var/log`, `/var/cache`, `/opt`). New secret stores must be
  added to `InaccessiblePaths` or placed under `/var/lib`.
- Abstract Unix sockets and listening localhost TCP/UDP services are reachable
  (shared network namespace); the D-Bus system bus is reachable as
  `lanectl-train`. The nix-daemon is reachable: a train can build and fetch
  into the shared store, as today.
- `/tmp` is private per unit, but trains share the host kernel, the
  `lanectl-train` UID and the nix store. There is no cross-train isolation:
  concurrent trains can signal each other, and same-UID `/proc` paths can expose
  a running sibling's tree despite the hidden direct spool paths.
- The coordinator is trusted: it can rename its own train dirs during prepare.
  The launcher uses fd-relative, no-follow operations, so this cannot direct
  root's chown outside the train dir, but it relies on `fs.protected_hardlinks`
  (systemd default 1) and on the hardlink refusal.
- Per-train `HOME` means no reusable build caches across trains until a cache
  policy is designed.
- Memory, process count and disk quotas remain unchanged and unbounded. Treat
  handed-back files as hostile input: never execute their Git config, filters or
  hooks as the coordinator, and never follow candidate symlinks while inspecting.
- Not yet qualified on the real host: the Sovite suite parity and the lanectl
  negative-probe harness (design doc tests 1-5) remain the gate. The VM test
  `nix build .#lanectl-train-fence-vm-test` covers the fence mechanics only.
