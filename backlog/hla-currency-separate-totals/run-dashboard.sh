#!/usr/bin/env bash
# Run from the candidate root inside the actual lanectl fence with owned deps.
set -euo pipefail
: "${CURRENCY_ACCEPTANCE_POSTGRES_DSN:?isolated UTF-8 PostgreSQL DSN required}"
: "${CURRENCY_ACCEPTANCE_HTTP_PORT:?free mixed backend port required}"
: "${CURRENCY_ACCEPTANCE_WEB_PORT:?free mixed frontend port required}"
: "${CURRENCY_ACCEPTANCE_UI_REPORT:?new absolute JSON report path required}"
[[ "$CURRENCY_ACCEPTANCE_UI_REPORT" = /* && ! -e "$CURRENCY_ACCEPTANCE_UI_REPORT" ]] || { echo "UI report must be a new absolute path" >&2; exit 1; }
command -v node >/dev/null
command -v curl >/dev/null
command -v setsid >/dev/null
command -v ps >/dev/null
source tools/project-env.sh
qualification_dir="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"
source "$qualification_dir/process-groups.sh"
export CURRENCY_ACCEPTANCE_API_URL="http://127.0.0.1:$CURRENCY_ACCEPTANCE_HTTP_PORT"
export CURRENCY_ACCEPTANCE_WEB_URL="http://127.0.0.1:$CURRENCY_ACCEPTANCE_WEB_PORT"
export CURRENCY_ACCEPTANCE_DISJOINT_API_URL="$CURRENCY_ACCEPTANCE_API_URL"
export CURRENCY_ACCEPTANCE_DISJOINT_WEB_URL="$CURRENCY_ACCEPTANCE_WEB_URL"
.venv/bin/python - "$CURRENCY_ACCEPTANCE_HTTP_PORT" "$CURRENCY_ACCEPTANCE_WEB_PORT" <<'PY'
import socket, sys
sockets = []
try:
    for port in sys.argv[1:]:
        s = socket.socket()
        s.bind(('127.0.0.1', int(port)))
        sockets.append(s)
finally:
    for s in sockets:
        s.close()
PY
logdir="$(mktemp -d -t currency-ui-logs.XXXXXXXX)"
backend_pid= web_pid= runner_pid=
cleanup() {
  local status=$? failed=0 pgid
  trap - EXIT INT TERM
  for pgid in "$runner_pid" "$web_pid" "$backend_pid"; do
    [[ -n "$pgid" ]] || continue
    if dev_stop_process_group "$pgid"; then
      wait "$pgid" 2>/dev/null || true
    else
      failed=1
    fi
  done
  rm -rf "$logdir" || failed=1
  [[ "$failed" == 0 ]] || status=1
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
run_phase() {
  local scenario="$1" selector="$2" pattern="$3" report="$4" deadline ready=0
  [[ ! -e "$report" ]] || { echo "Report already exists: $report" >&2; return 1; }
  setsid env CURRENCY_ACCEPTANCE_SCENARIO="$scenario" .venv/bin/python tests/currency_dashboard_fixture.py >"$logdir/$scenario-fixture.log" 2>&1 & backend_pid=$!
  setsid env HOMELAB_ANALYTICS_API_BASE_URL="$CURRENCY_ACCEPTANCE_API_URL" node apps/web/frontend/node_modules/next/dist/bin/next dev apps/web/frontend -H 127.0.0.1 -p "$CURRENCY_ACCEPTANCE_WEB_PORT" >"$logdir/$scenario-next.log" 2>&1 & web_pid=$!
  deadline=$((SECONDS + 60))
  while (( SECONDS < deadline )); do
    for pgid in "$backend_pid" "$web_pid"; do
      kill -0 "$pgid" 2>/dev/null || { cat "$logdir/$scenario-fixture.log" "$logdir/$scenario-next.log"; return 1; }
    done
    if curl --connect-timeout 1 --max-time 2 -fsS "$CURRENCY_ACCEPTANCE_API_URL/reports/monthly-cashflow" >/dev/null 2>&1 && \
       curl --connect-timeout 1 --max-time 2 -fsS "$CURRENCY_ACCEPTANCE_WEB_URL/" >/dev/null 2>&1; then ready=1; break; fi
    sleep 1
  done
  [ "$ready" = 1 ] || { cat "$logdir/$scenario-fixture.log" "$logdir/$scenario-next.log"; return 1; }
  export PLAYWRIGHT_JSON_OUTPUT_FILE="$report"
  (cd apps/web/frontend && exec setsid node node_modules/@playwright/test/cli.js test playwright/currency-separate-totals.spec.js --project=chromium --reporter=line,json "$selector" "$pattern") & runner_pid=$!
  if wait "$runner_pid"; then phase_status=0; else phase_status=$?; fi
  for pgid in "$runner_pid" "$web_pid" "$backend_pid"; do
    if dev_stop_process_group "$pgid"; then wait "$pgid" 2>/dev/null || true; else return 1; fi
  done
  runner_pid= web_pid= backend_pid=
}
run_phase mixed --grep-invert 'disjoint household|scenario projection' "$CURRENCY_ACCEPTANCE_UI_REPORT.mixed.json"
mixed_status=$phase_status
run_phase disjoint --grep 'disjoint household' "$CURRENCY_ACCEPTANCE_UI_REPORT.disjoint.json"
disjoint_status=$phase_status
run_phase scenario-eur --grep 'scenario projection currency oracle|scenario projection EUR' "$CURRENCY_ACCEPTANCE_UI_REPORT.scenario-eur.json"
eur_status=$phase_status
run_phase scenario-usd --grep 'scenario projection USD' "$CURRENCY_ACCEPTANCE_UI_REPORT.scenario-usd.json"
usd_status=$phase_status
.venv/bin/python - "$CURRENCY_ACCEPTANCE_UI_REPORT" "$mixed_status" "$disjoint_status" "$eur_status" "$usd_status" <<'PY'
import json, sys
try:
    output = sys.argv[1]
    reports = []
    for suffix in ('.mixed.json', '.disjoint.json', '.scenario-eur.json', '.scenario-usd.json'):
        with open(output + suffix) as f:
            reports.append(json.load(f))
    specs = []
    def walk(suite):
        specs.extend(suite.get('specs', []))
        for child in suite.get('suites', []):
            walk(child)
    for report in reports:
        for suite in report['suites']:
            walk(suite)
    expected = {'visible amount oracle rejects larger and hidden values', 'fixture serves every published currency group', 'dashboard visibly retains both cashflow groups', 'dashboard visibly retains both utility groups', 'disjoint household report retains finance and utility units', 'disjoint household visibly retains finance and utility units', 'scenario projection currency oracle rejects ambiguous and missing values', 'scenario projection EUR has coherent currency', 'scenario projection USD has coherent currency'}
    assert sys.argv[2:] == ['0', '0', '0', '0'] and all(not r['errors'] for r in reports)
    assert {x['title'] for x in specs} == expected and len(specs) == len(expected)
    assert sum(r['stats']['expected'] for r in reports) == len(expected)
    assert all(r['stats'][key] == 0 for r in reports for key in ('skipped', 'unexpected', 'flaky'))
    assert all(len(spec['tests']) == 1 and len(spec['tests'][0]['results']) == 1
               and spec['tests'][0]['results'][0]['status'] == 'passed' for spec in specs)
except (OSError, KeyError, ValueError, AssertionError, TypeError) as exc:
    raise SystemExit(f'UI qualification rejected: all exact tests must execute and pass: {exc}')
with open(output, 'x') as f:
    json.dump({'mixed': reports[0], 'disjoint': reports[1], 'scenario_eur': reports[2], 'scenario_usd': reports[3]}, f)
PY
