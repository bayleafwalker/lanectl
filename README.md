# lanectl

Autonomous implementation lanes. Cheap workers (OpenCode Go DeepSeek V4.1 Flash
first) implement planner-written WorkReleases in isolated worktrees; deterministic
gates decide preliminary acceptance; an integrator lands candidate trains.

Design and invariants: [ADR 0001](docs/adr/0001-autonomous-lanes.md).
Planner cycle: [.claude/skills/lane-planner/SKILL.md](.claude/skills/lane-planner/SKILL.md).

```sh
lanectl doctor                         # is the estate healthy?
lanectl backlog list --open            # what is open, and in what state
lanectl backlog new <id> --repo R --title T --scope 'src/**'   # scaffold a draft release
lanectl backlog publish <id>           # lint and release it to the lanes
lanectl run --max 3                    # lanes implement ready releases
lanectl candidates && lanectl train <repo> && lanectl land <train_id>
lanectl deploy run <train_id>          # repos with [deploy]: dev deploy + health before land
lanectl deploy list | reap             # live dev deploys; tear down expired/landed/superseded
lanectl lanes | report | view --html out.html   # caps, precision and cost, management page
lanectl focus <id> [--role integrator]  # attribute this Claude session's usage to a release
lanectl tick                           # doctor + deploy reap + run (contrib/systemd timer)
lanectl otel export --out spans.json   # OTLP/JSON spans for an OTel collector
```

Run inside the checkout, or set `$LANECTL_HOME`.

Per-repo gate jobs (`[[repos.<r>.gate_jobs]]`) run in the attempt sandbox after acceptance;
dev deploys (`[repos.<r>.deploy]`) run on passed trains with a stripped environment. See
[stage 3 plan](docs/plans/2026-11-10-stage3-gate-jobs-and-train-deploys.md).

State: `$LANECTL_STATE` (default `~/.local/state/lanectl/events.jsonl`).
Governance and backlog: `$LANECTL_HOME` (a checkout of this repo's main).
