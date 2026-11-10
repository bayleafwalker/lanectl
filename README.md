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
lanectl lanes | report | view --html out.html   # caps, precision and cost, management page
```

Run inside the checkout, or set `$LANECTL_HOME`.

State: `$LANECTL_STATE` (default `~/.local/state/lanectl/events.jsonl`).
Governance and backlog: `$LANECTL_HOME` (a checkout of this repo's main).
