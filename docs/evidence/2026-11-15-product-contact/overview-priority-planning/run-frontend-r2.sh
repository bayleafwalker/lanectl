#!/usr/bin/env bash
set +e
r=/tmp/hla-overview-priority-prerequisite-20261115
cd "$r" || exit 90
env -i HOME="$r/home" XDG_CACHE_HOME="$r/cache" TMPDIR="$r/tmp" PATH=/run/current-system/sw/bin:/usr/bin:/bin LANG=C.UTF-8 /projects/dev/homelab-analytics/.tooling/node-v20.20.1-linux-x64/bin/node "$r/frontend-probe-r2.cjs" > "$r/frontend-r2.stdout" 2> "$r/frontend-r2.stderr"
status=$?
printf '%s\n' "$status" > "$r/frontend-r2.exit"
exit "$status"
