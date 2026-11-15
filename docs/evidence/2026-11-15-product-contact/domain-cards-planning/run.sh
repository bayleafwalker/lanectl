#!/usr/bin/env bash
set +e
cd /projects/dev/homelab-analytics || exit 90
claude -p --model claude-opus-5-5 --output-format json --permission-mode plan --tools Read,Grep,Glob --allowedTools Read Grep Glob --disallowedTools 'Read(**/error.log)' -- < /tmp/hla-domain-cards-plan-20261115/prompt.txt > /tmp/hla-domain-cards-plan-20261115/native.json 2> /tmp/hla-domain-cards-plan-20261115/native.stderr
status=$?
printf '%s\n' "$status" > /tmp/hla-domain-cards-plan-20261115/native.exit
exit "$status"
