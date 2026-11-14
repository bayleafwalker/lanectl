#!/bin/sh
set +e
/nix/store/71c91xjkcj07khl9imgmgji5wzrxwy65-gnumake-4.4.1/bin/make verify-fast > /tmp/hla-boundary-a3-qualification-20261114/final-make.log 2>&1
rc=$?
printf '%s\n' "$rc" > /tmp/hla-boundary-a3-qualification-20261114/final-make-exit.tmp
mv /tmp/hla-boundary-a3-qualification-20261114/final-make-exit.tmp /tmp/hla-boundary-a3-qualification-20261114/final-make-exit.txt
exit "$rc"
