#!/usr/bin/env bash
set +e
r=/tmp/hla-overview-priority-prerequisite-20261115
cd "$r" || exit 90
lib=$(for d in /nix/store/*-gcc-*-lib/lib; do [ -f "$d/libstdc++.so.6" ] && printf '%s' "$d" && break; done)
env -i HOME="$r/home" XDG_CACHE_HOME="$r/cache" TMPDIR="$r/tmp" PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/projects/dev/homelab-analytics PATH=/run/current-system/sw/bin:/usr/bin:/bin LANG=C.UTF-8 LD_LIBRARY_PATH="$lib" /projects/dev/homelab-analytics/.venv/bin/python "$r/tie-probe.py" > "$r/tie.stdout" 2> "$r/tie.stderr"
status=$?
printf '%s\n' "$status" > "$r/tie.exit"
exit "$status"
