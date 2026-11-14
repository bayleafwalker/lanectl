# Namespace command completion repair — lanectl#2902

The installed 0.2.11 namespace path returned zero when an exact systemd unit was
stopped before the candidate check completed. Real red regressions also observed
build and recheck marked PASSED and historical landing accepted. No real product
train was knowingly adopted under this incomplete-stop condition.

The train-only repair uses a oneshot start deadline and a fixed parent shell
that returns failure on termination even when the candidate traps TERM and exits
zero. Worker shims and the strict separate-UID receipt backend are unchanged.
The stop limit is 15 seconds within the existing 1830-second outer timeout.

The native Sonnet 5.5 source review cleared immutable 7842494 with low test and
documentation suggestions, now addressed. Executable ASTs are unchanged after
review. The final required suite passed 1120 tests. The actual-source experiment
measured a TERM-ignoring child stopped in 15.03 seconds, nonzero check status,
completion absent after acknowledgement, and all three recorded processes gone.
Original quoting-fixture mistakes are retained with the corrected exact probe.

The experiments are bounded evidence on systemd 262, not a claim about every
scheduling interleaving, arbitrary hostile same-UID code, or cleanup after manager
communication loss. Outer timeouts fail the result but alone do not prove cleanup.
The first oneshot-only experiment was falsified by a child TERM trap exiting zero;
its failed results are retained alongside the parent and combined prototypes.

Raw /tmp originals are ephemeral. This directory becomes cross-host-replicated
after canonical Git push. Served item 2902 is durable-authoritative work state.
Release and installed byte verification are recorded separately after rollout.
