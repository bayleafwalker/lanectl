#!/usr/bin/env bash
set +e
role="god-class-file-size-supplement"
r=/tmp/hla1597-unit-review-20261115/followup
cd /projects/dev/_wt/hla1597-unit-20261115 || exit 90
claude -p --restricted --strict-mcp-config --model claude-sonnet-5-5 --output-format json --permission-mode dontAsk --tools Read,Grep,Glob --allowedTools Read Grep Glob --disallowedTools 'Read(**/error.log)' --add-dir /tmp/hla1597-unit-review-20261115 --add-dir /tmp/hla1597-integration-20261115 -- < "$r/$role.prompt.txt" > "$r/$role.native.json" 2> "$r/$role.stderr"
status=$?
printf '%s\n' "$status" > "$r/$role.exit"
exit "$status"
