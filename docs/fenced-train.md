# Separate-UID train execution

Version 0.2.5 adds `train_isolation = "systemd"` as an opt-in repository mode.
It uses the fixed root-owned `lanectl-train@.service` template. A launch or
qualification failure returns a failed command; it never selects another mode.
Namespace remains the default. Coordinated work refuses environment-only mode.

The host must install the reviewed account, template, launcher, spool, outside-tree
receipt directory and narrow coordinator authorization. The implemented host is
gitops-nixos commit `dbf142e2636d0397c7aeb5cacad3b4b1adfe2df4`; its runbook is
`docs/runbooks/lanectl-train-fence.md` in that repository. The workstation now has
UID/GID1120, a non-login account, coordinator-owned 0700 spool and root-owned 0755
receipt directory. No general sudo grant is used.

Each command gets a fresh self-contained checkout and private home. Setup runs
inside the same fence before a check. Nothing is copied back. The client accepts
only a coherent root-owned receipt bound to the exact request and nonce, after
terminal state and ownership handback. Failed or uncertain stop acknowledgement
retains a named orphan; remove it only after proving the exact service stopped.

The installed-service qualification matches Sovite's ordinary baseline:
2,797 passed / 1,140 skipped. Synthetic probes deny 24 read/write opens, strip secret
environment names, preserve checkout writes and observe root/nix UID 0 with the
train at UID 1120. Actual build, recheck, historical reconstruction, timeout,
cancellation and deliberate lost-stop acknowledgement also pass. Raw evidence
and reproducible harnesses are in
[`docs/evidence/2026-11-13-fenced-client/`](evidence/2026-11-13-fenced-client/).

Qualify the selected repository before changing its policy. Additional direct
systemd smoke tests found concrete limits:

- Appservice's full validator passes when setup supplies its public origin URL.
  Staging deliberately discards source remote configuration; credentials and
  arbitrary Git configuration must never be copied to restore metadata.
- Homelab-analytics needs its documented DuckDB library-loader context. Its
  self-contained Makefile path also needs `make` on the fixed host tool path.
- Lanectl's own integration suite needs a nested user manager; the dedicated
  system account does not currently provide one. Its configured namespace suite
  passes 989 tests. Do not weaken those tests to qualify systemd mode.

The dedicated UID is shared by trains, so sibling processes remain a residual
boundary. Network behavior is unchanged. This backend does not establish hosted
runner authentication or complete the delivery ladder's operational clocks.
