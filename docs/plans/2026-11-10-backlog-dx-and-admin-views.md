# Backlog DX and admin views (2026-11-10)

Operator direction, 2026-11-10: build out lanectl's backlog functionality for a full
developer experience, add management and admin views, troubleshoot and fix what the
operator hits, and use lanectl itself to build it. The planner writes contracts and
acceptance tests; lanes implement; the integrator lands trains after review.

## What the operator hits today (observed 2026-11-10)

| Problem | Evidence |
| --- | --- |
| `status` lists every landed item and a JSON blob; open work is buried | 41 landed rows before anything actionable |
| `ready` reports landed releases as READY | every historical release prints READY |
| No way to see the backlog as a list with state, or one release with its attempts | needs `status` + `events --item` + reading `release.toml` |
| Writing a release is manual: copy a toml, look up `base_sha`, bump revisions by hand | planner skill steps 3 and the stale-base rule |
| Governance is not found unless `LANECTL_HOME` is exported | `lanectl capacity` printed "no allocation policy" from the checkout |
| No health check: broken releases, stale attempts, drifted bases and an old runner surface only as failures | 2026-11-08 runner crash on an unknown event type |
| No view of lanes: routing, caps and how much of each cap is in use | caps live in toml; usage only in the log |
| `report` truncates class and model names to 10 characters | `opencode-g`, `test-gener` |
| `cost_feedback` attempts (claims, 71) and `report` ATT (experiments, 67) disagree with no label | 4 attempts stopped by infra before an experiment |

## Outcomes

Wave 1 (independent modules; plugin commands register themselves, so no `cli.py` contention
except `bx-open-default`):

| Release | Outcome |
| --- | --- |
| `bx-backlog` | `lanectl backlog list` (state, filters, summary, JSON) and `backlog show <id>` |
| `bx-open-default` | `status` and `ready` show open work by default; `--all` keeps history |
| `bx-home-default` | without `LANECTL_HOME`, find the checkout by walking up from the working directory |
| `bx-doctor` | `lanectl doctor`: home, releases, repos, log, policy, stale attempts, drifted bases |
| `bx-lanes` | `lanectl lanes`: per-lane routing, limits and live cap usage |
| `bx-report-polish` | full names in report tables; infra-stopped attempts labelled in cost feedback |

Wave 2 (builds on wave 1):

| Release | Outcome |
| --- | --- |
| `bx-backlog-new` | `backlog new` scaffolds a valid release at the repo's current main; `backlog rebase` moves pending releases to main and bumps revision |
| `bx-admin-view` | `view --html` gains backlog, attention (parked, open, candidates), lanes and governance sections |
| `bx-cost-usd` | dollar estimates from a published price table, so cost is not reported as 0.0 |
| `bx-burn-min-window` | burn takes the minimum across windows with per-window usage (sprintctl lanectl#2881) |

## Constraints

- Releases are size S or M, `data_class = "public"`, acceptance in `tests/stage8/`.
- No new event types: views read the existing log. Backlog scaffolding writes only under
  `backlog/` in the planner's checkout, never in a lane's scope.
- `bx-backlog-new` writes planner-owned files; lanes may build the tool, but it is run by the
  planner, and `backlog/**` stays a protected path for lanes.

## Assessment

Recorded at closeout: accepted outcomes, planner effort, fix classes, elapsed time.
