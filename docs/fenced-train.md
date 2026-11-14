# Separate-UID train execution

Version 0.2.5 adds `train_isolation = "systemd"` as an opt-in repository mode.
It uses the fixed root-owned `lanectl-train@.service` template. A launch or
qualification failure returns a failed command; it never selects another mode.
Namespace remains the default. Coordinated work refuses environment-only mode.

The host must install the reviewed account, template, launcher, spool,
outside-tree receipt directory and narrow coordinator authorization. On
2026-11-14 the workstation was observed running gitops-nixos revision
`2e77a4eca60a4338aeab00b8f48756916c93d226` with
`RootDirectory=/run/lanectl-train/.rootfs` and UID/GID1120. The account has no
login shell; the spool is coordinator-owned 0700 and receipts are root-owned.
No general sudo grant is used.

The earlier `dbf142e` generation exposed undeclared host files through a
read-only host tree. The applied correction uses an empty root and explicit
read-only inputs. Its live public-canary probe now rejects `/etc/issue`; the
unfenced control can open it. The installed unit and launcher exactly match the
reviewed source and evaluated build. The running whole-system output differs
from the helper build through Home Manager wallpaper executable modes; that
source-accessor discrepancy remains unresolved. This qualification binds the
fence, not equality of the entire system closures. See the
[host binding](evidence/2026-11-14-strict-host/host-binding.json).

The current strict-root run matches Sovite's clean baseline: 2,797 passed and
1,140 skipped, with no failure or error markers. Both setup and check exited
successfully. Pytest's double-quiet output omits a summary, so counts are
independently parsed from the retained progress lines. Boundary, DNS/TLS,
setup/check/recheck/historical recovery, timeout, cancellation and lost-stop
acknowledgement probes passed. Seven retained unit names are inactive with
spools removed; some other successful harness calls did not retain unit names
and cannot be individually re-audited. See the
[raw evidence and parser](evidence/2026-11-14-strict-host/summary.json).

Sovite now selects `systemd` after independent review and the required
repository regressions passed. A normal configured canary, without a backend
override, reran repository setup and verified UID1120, root/nix UID0, checkout
writes and the absent undeclared host file. The policy tests passed38 cases.
Other repositories retain namespace mode: lanectl passed1,038 tests, appservice
passed its configured validator, and HLA passed2,715 tests plus120 subtests with
one existing make-unavailable skip. Candidate HLA delivery separately runs its
full verification with the required make/browser tools.

Each command gets a fresh self-contained checkout and private home. Setup runs
inside the same fence before a check. Nothing is copied back. The client accepts
only a coherent root-owned receipt bound to the exact request and nonce, after
terminal state and ownership handback. Failed or uncertain stop acknowledgement
retains a named orphan; remove it only after proving the exact service stopped.

Historical qualification and reproducible harness reviews remain in
[`docs/evidence/2026-11-13-fenced-client/`](evidence/2026-11-13-fenced-client/).
The current strict-root probe rejects 26 read/write opens to 13 denied paths,
strips synthetic secret environment names, preserves checkout writes and
observes root/nix UID 0 with the train at UID 1120.

Qualify the selected repository before changing its policy. Additional direct
systemd smoke tests found concrete limits:

- Appservice's full validator passes when setup supplies its public origin URL.
  Staging deliberately discards source remote configuration; credentials and
  arbitrary Git configuration must never be copied to restore metadata.
- Homelab-analytics needs its documented DuckDB library-loader context. Its
  self-contained Makefile path also needs `make` on the fixed host tool path.
- Lanectl's own integration suite needs a nested user manager; the dedicated
  system account does not currently provide one. Its historical configured
  namespace suite passed 1,008 tests in release 0.2.6. Do not weaken those tests
  to qualify systemd mode.

## Runtime and boundary contract

The host launcher supplies `PATH=/run/current-system/sw/bin`, `LANG=C.UTF-8`
and the system CA bundle. Required tools must exist there or be installed by
trusted repository setup inside the fresh checkout. `make` and `node` are not
currently on that fixed host PATH. Appservice provisions its own tools with
mise; HLA's DuckDB check also needs its documented shared-library loader setup.
Source Git remotes, configuration, credentials, virtual environments and caches
are not copied. Every fresh command reruns setup, so setup must be self-contained.

`HOME` is a new directory under that train's checkout. `TMPDIR=/tmp`, `/tmp`,
`/var/tmp` and devices are private to the unit. The static UID/GID is 1120;
there is no user namespace or ownership remapping, so `/` and `/nix` retain
UID 0. Among persistent host directories, only the per-command checkout is
writable by the candidate. Canonical
repositories, coordinator state and governance are inaccessible: the candidate
does not read those originals. The coordinator stages the approved source before
launch and inspects the handed-back tree without running candidate Git commands.
Read-only inputs such as `/nix` and the hosts file are a separate boundary;
successful reads and denied writes are probed explicitly.

The strict host correction declares only `/nix`, `/run/current-system`, `/bin/sh`,
`/usr/bin/env`, resolver/hosts/NSS files, passwd/group and the CA bundle as
mandatory read-only host inputs, plus systemd's API filesystems and host
`os-release` metadata. Missing mandatory inputs prevent execution. No sibling
checkout is bound. The root receipt directory is visible for the fixed root
post-step; candidate writes are denied by root ownership. The host runbook owns
the exact manifest and its VM falsifiers. The installed unit matches the source-checked manifest. Live probes exercise
selected inputs and denials; the source-bound VM also forces a missing
mandatory input to fail before candidate execution.

Subprocesses stay in the systemd control group even after `setsid`. Actual-host
cancellation observed a live escaped child, acknowledged one stop, then proved
that child was gone and the checkout removed. The launcher enforces the request
deadline; systemd also provides a hard runtime cap. Ownership handback may take
up to the host's 600-second stop limit. A refused, failed or timed-out stop
acknowledgement retains a named orphan for explicit recovery.

Trains share a UID and host process namespace. They can signal sibling processes
and same-UID `/proc` paths remain a residual exposure; this is not cross-train
process isolation. Network egress and reachable network services remain unchanged.
The strict root does not bind host D-Bus or journal socket paths, but abstract
sockets and network endpoints remain outside the filesystem boundary. The Nix
store is readable, so it must not contain secrets. There are no disk/CPU quotas
or reusable candidate home caches. Native workers retain their own authenticated
environments outside the train; the committed adapter/attempt events demonstrate
actual Claude and Go authentication beside the candidate credential-denial probes.

The dedicated UID is shared by trains, so sibling processes remain a residual
boundary. Network behavior is unchanged. This backend does not establish hosted
runner authentication or complete the delivery ladder's operational clocks.

The current installed client is 0.2.9 at
`f9267ea32e481f2a1ecf3f57b07ff0e888e1d0cf`; its runtime bytes match the reviewed
publication-evidence repair. See the
[installation evidence](evidence/2026-11-13-product-contact/lanectl-v029-installed.json).
The current strict-root evidence above uses this installed client. It does not
establish hosted runner authentication or the ladder's operational clocks.
