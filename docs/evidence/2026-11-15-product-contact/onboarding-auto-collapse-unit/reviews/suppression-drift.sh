#!/usr/bin/env bash
set +e
role="suppression-drift"
root=/tmp/hla1597-unit-review-20261115
cd /projects/dev/_wt/hla1597-unit-20261115 || exit 90
claude -p --restricted --strict-mcp-config --model claude-sonnet-5-5 --output-format json --permission-mode dontAsk --tools Read,Grep,Glob --allowedTools Read Grep Glob --disallowedTools 'Read(**/error.log)' --add-dir "$root" -- < "$root/$role.prompt.txt" > "$root/$role.native.json" 2> "$root/$role.stderr"
status=$?
printf '%s\n' "$status" > "$root/$role.exit"
exit "$status"
