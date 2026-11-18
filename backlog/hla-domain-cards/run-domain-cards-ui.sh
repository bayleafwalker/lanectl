#!/usr/bin/env bash
# Owner-run browser qualifier from a clean HLA candidate with its locked setup.
set -euo pipefail
: "${DOMAIN_CARDS_POSTGRES_DSN:?isolated PostgreSQL DSN required}"
: "${DOMAIN_CARDS_REPORT_DIR:?new absolute report directory required}"
[[ "$DOMAIN_CARDS_REPORT_DIR" == /* && ! -e "$DOMAIN_CARDS_REPORT_DIR" ]]
[[ -z "$(git status --porcelain)" ]]
head=$(git rev-parse HEAD)
parent=$(git log -1 --format=%P)
criterion_dir=$(dirname "$(realpath "${BASH_SOURCE[0]}")")
source "$criterion_dir/../hla-currency-separate-totals/process-groups.sh"
cp_check=()
files=(apps/web/frontend/playwright/domain-cards.spec.js tests/domain_cards_fixture.py tests/test_acc_domain_cards.py)
[[ "$parent" =~ ^[[:xdigit:]]{40}$ ]]
[[ "$(git diff --name-only "$parent" "$head")" == "$(printf '%s\n' "${files[@]}")" ]]
for relative in "${files[@]}"; do
  cmp "$relative" "$criterion_dir/files/$relative"
  cp_check+=("$relative" "$criterion_dir/files/$relative")
done
source tools/project-env.sh
duckdb_path="${LD_LIBRARY_PATH:-}"
source tools/dev-env.sh
source tools/dev-browser.sh
dev_prepare_env "$PWD"
dev_prepare_browser_env "$PWD"
mkdir "$DOMAIN_CARDS_REPORT_DIR"
sha256sum "$criterion_dir/release.toml" "$criterion_dir/run-domain-cards-ui.sh" \
  "$criterion_dir/../hla-currency-separate-totals/process-groups.sh" "${cp_check[@]}" > "$DOMAIN_CARDS_REPORT_DIR/source-sha256.txt"
printf '%s\n' "$head" > "$DOMAIN_CARDS_REPORT_DIR/candidate-commit.txt"
printf '%s\n' "$parent" > "$DOMAIN_CARDS_REPORT_DIR/production-parent.txt"
owned=()
settle() {
  local bad=0 pid
  for pid in "${owned[@]}"; do
    if dev_stop_process_group "$pid"; then
      wait "$pid" 2>/dev/null || true
    else
      bad=1
    fi
  done
  owned=()
  return "$bad"
}
trap 'settle || exit 1' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
status=0
for scenario in normal empty unavailable; do
  ports=$(.venv/bin/python -c 'import socket; sockets=[socket.socket(),socket.socket()]; [s.bind(("127.0.0.1",0)) for s in sockets]; print(*(s.getsockname()[1] for s in sockets))')
  read -r DOMAIN_CARDS_API_PORT web_port <<< "$ports"
  export DOMAIN_CARDS_SCENARIO="$scenario" DOMAIN_CARDS_API_PORT
  export DOMAIN_CARDS_WEB_URL="http://127.0.0.1:$web_port/operating-picture"
  export HOMELAB_ANALYTICS_API_BASE_URL="http://127.0.0.1:$DOMAIN_CARDS_API_PORT"
  export PLAYWRIGHT_JSON_OUTPUT_FILE="$DOMAIN_CARDS_REPORT_DIR/$scenario.json"
  LD_LIBRARY_PATH="$duckdb_path" setsid .venv/bin/python tests/domain_cards_fixture.py > "$DOMAIN_CARDS_REPORT_DIR/$scenario-api.log" 2>&1 &
  owned+=("$!")
  setsid node apps/web/frontend/node_modules/next/dist/bin/next dev apps/web/frontend -H 127.0.0.1 -p "$web_port" > "$DOMAIN_CARDS_REPORT_DIR/$scenario-web.log" 2>&1 &
  owned+=("$!")
  ready=0
  for ((i=0; i<40; i++)); do
    for pid in "${owned[@]}"; do kill -0 "$pid"; done
    if curl -fsS --max-time 2 "$HOMELAB_ANALYTICS_API_BASE_URL/health" >/dev/null && \
      curl -fsS --max-time 2 "$DOMAIN_CARDS_WEB_URL" >/dev/null; then
      ready=1
      break
    fi
    sleep 1
  done
  [[ "$ready" == 1 ]]
  case "$scenario" in
    normal) selector='show observed headlines' ;;
    *) selector='keep empty sources distinct' ;;
  esac
  (cd apps/web/frontend && exec setsid node node_modules/@playwright/test/cli.js test playwright/domain-cards.spec.js --project=chromium --reporter=json --grep "$selector") &
  owned=("$!" "${owned[@]}")
  wait "${owned[0]}" || status=1
  settle
done
test -z "$(git status --porcelain)"
test "$(git rev-parse HEAD)" = "$head"
sha256sum --check "$DOMAIN_CARDS_REPORT_DIR/source-sha256.txt"
.venv/bin/python - "$DOMAIN_CARDS_REPORT_DIR" "$status" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
titles = {
    "normal": "domain cards show observed headlines trends and source attention",
    "empty": "domain cards keep empty sources distinct from unavailable",
    "unavailable": "domain cards keep empty sources distinct from unavailable",
}
for scenario, title in titles.items():
    report = json.loads((root / f"{scenario}.json").read_text())
    def specs(suite):
        yield from suite.get("specs", [])
        for child in suite.get("suites", []):
            yield from specs(child)
    cases = [case for suite in report["suites"] for case in specs(suite)]
    assert not report["errors"] and report["stats"]["expected"] == 1, scenario
    assert all(report["stats"][key] == 0 for key in ("skipped", "unexpected", "flaky")), scenario
    assert len(cases) == 1 and cases[0]["title"] == title, scenario
    [test] = cases[0]["tests"]
    [result] = test["results"]
    assert result["status"] == "passed", scenario
assert sys.argv[2] == "0"
PY
