#!/usr/bin/env bash
set +e
r=/tmp/hla-overview-priority-prerequisite-20261115
cd /projects/dev/homelab-analytics || exit 90
claude -p --restricted --strict-mcp-config --model claude-opus-5-5 --output-format json --permission-mode dontAsk --tools Read,Grep,Glob --allowedTools Read Grep Glob --disallowedTools 'Read(**/error.log)' -- < "$r/prompt.txt" > "$r/native.json" 2> "$r/native.stderr"
status=$?
printf '%s\n' "$status" > "$r/native.exit"
exit "$status"
