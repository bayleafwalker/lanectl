# lanectl

Autonomous implementation lanes. Cheap workers (OpenCode Go DeepSeek V4.1 Flash
first) implement planner-written WorkReleases in isolated worktrees; deterministic
gates decide preliminary acceptance; an integrator lands candidate trains.

Design and invariants: [ADR 0001](docs/adr/0001-autonomous-lanes.md).
Planner cycle: [.claude/skills/lane-planner/SKILL.md](.claude/skills/lane-planner/SKILL.md).

```sh
lanectl ready | status | candidates
lanectl run --max 3
lanectl train <repo> && lanectl land <train_id>
```

State: `$LANECTL_STATE` (default `~/.local/state/lanectl/events.jsonl`).
Governance and backlog: `$LANECTL_HOME` (a checkout of this repo's main).
