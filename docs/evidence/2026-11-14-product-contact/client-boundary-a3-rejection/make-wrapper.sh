#!/bin/sh
set +e
/nix/store/71c91xjkcj07khl9imgmgji5wzrxwy65-gnumake-4.4.1/bin/make verify-fast
rc=$?
printf '%s\n' "$rc" > /tmp/hla-boundary-a3-qualification-20261114/make-exit.tmp
mv /tmp/hla-boundary-a3-qualification-20261114/make-exit.tmp /tmp/hla-boundary-a3-qualification-20261114/make-exit.txt
exit "$rc"
