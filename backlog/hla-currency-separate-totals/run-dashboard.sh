#!/usr/bin/env bash
# Run from the candidate root inside the actual lanectl fence with owned deps.
set -euo pipefail
: "${CURRENCY_ACCEPTANCE_POSTGRES_DSN:?isolated UTF-8 PostgreSQL DSN required}"
: "${CURRENCY_ACCEPTANCE_HTTP_PORT:?free loopback backend port required}"
: "${CURRENCY_ACCEPTANCE_WEB_PORT:?free loopback frontend port required}"
: "${CURRENCY_ACCEPTANCE_UI_REPORT:?new absolute JSON report path required}"
[[ "$CURRENCY_ACCEPTANCE_UI_REPORT" = /* && ! -e "$CURRENCY_ACCEPTANCE_UI_REPORT" ]] || { echo "UI report must be a new absolute path" >&2; exit 1; }
command -v node >/dev/null
command -v curl >/dev/null
source tools/project-env.sh
export HOMELAB_ANALYTICS_API_BASE_URL="http://127.0.0.1:$CURRENCY_ACCEPTANCE_HTTP_PORT"
export CURRENCY_ACCEPTANCE_API_URL="$HOMELAB_ANALYTICS_API_BASE_URL"
export CURRENCY_ACCEPTANCE_WEB_URL="http://127.0.0.1:$CURRENCY_ACCEPTANCE_WEB_PORT"
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
.venv/bin/python tests/currency_dashboard_fixture.py >currency-fixture.log 2>&1 &
backend_pid=$!
(cd apps/web/frontend && exec node node_modules/next/dist/bin/next dev -H 127.0.0.1 -p "$CURRENCY_ACCEPTANCE_WEB_PORT") >currency-next.log 2>&1 &
web_pid=$!
cleanup() { kill "$backend_pid" "$web_pid" 2>/dev/null || true; wait "$backend_pid" "$web_pid" 2>/dev/null || true; }
trap cleanup EXIT
ready=0
for _ in $(seq 1 60); do
  kill -0 "$backend_pid" "$web_pid" 2>/dev/null || { cat currency-fixture.log currency-next.log; exit 1; }
  if curl -fsS "$CURRENCY_ACCEPTANCE_API_URL/reports/monthly-cashflow" >/dev/null 2>&1 && curl -fsS "$CURRENCY_ACCEPTANCE_WEB_URL/" >/dev/null 2>&1; then ready=1; break; fi
  sleep 1
done
[ "$ready" = 1 ] || { cat currency-fixture.log currency-next.log; exit 1; }
cd apps/web/frontend
export PLAYWRIGHT_JSON_OUTPUT_FILE="$CURRENCY_ACCEPTANCE_UI_REPORT"
set +e
node node_modules/@playwright/test/cli.js test playwright/currency-separate-totals.spec.js --project=chromium --reporter=line,json
status=$?
set -e
candidate_root="../../.."
"$candidate_root/.venv/bin/python" - "$CURRENCY_ACCEPTANCE_UI_REPORT" "$status" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as f:
        report = json.load(f)
    specs = []
    def walk(suite):
        specs.extend(suite.get('specs', []))
        for child in suite.get('suites', []):
            walk(child)
    for suite in report['suites']:
        walk(suite)
    expected = {'fixture serves every published currency group', 'dashboard visibly retains both cashflow groups', 'dashboard visibly retains both utility groups'}
    assert int(sys.argv[2]) == 0 and not report['errors']
    assert {x['title'] for x in specs} == expected and len(specs) == 3
    assert report['stats']['expected'] == 3
    assert all(report['stats'][key] == 0 for key in ('skipped', 'unexpected', 'flaky'))
    assert all(len(spec['tests']) == 1 and len(spec['tests'][0]['results']) == 1
               and spec['tests'][0]['results'][0]['status'] == 'passed' for spec in specs)
except (OSError, KeyError, ValueError, AssertionError, TypeError) as exc:
    raise SystemExit(f'UI qualification rejected: all three exact tests must execute and pass: {exc}')
PY
