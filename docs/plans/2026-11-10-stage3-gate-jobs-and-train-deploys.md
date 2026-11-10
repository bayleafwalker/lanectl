# Stage 3: gate jobs and dev train deploys (2026-11-10)

Operator direction, 2026-11-10: "proceed with the full implementation lane" after the
backlog-DX closeout named stage 3 (sprintctl lanectl#2882) as the open design. This plan is
the planner's design; lanes build it, the integrator lands it.

## Decisions

| Question (lanectl#2882) | Decision |
| --- | --- |
| Gate-job contract | `[[repos.<r>.gate_jobs]]` in `governance/repos.toml`: `name`, `cmd`, `timeout_s` (default 600). Each job runs in the attempt worktree, in the attempt sandbox (no network, no credentials), after the acceptance gate passes. Each job is its own gate `job:<name>` in the existing `gate.result` event; a non-zero exit or a timeout is a violation, so `decide()` rejects as for any gate. |
| Feeding evaluate | Through gate acceptance: an attempt that fails a job is never gate-accepted, so `evaluate` only sees attempts that passed every job. No evaluator feature is added until evidence shows one would predict an integrator ruling (evaluator rev 2 rule). |
| Which repos get a dev deploy | Repos that declare `[repos.<r>.deploy]`. First: homelab-analytics, which already has an isolated compose smoke stack. lanectl, sovite and vuoro-cloud declare none. |
| Deploy mechanism | Direct, not GitOps. `lanectl deploy <train_id>` runs the repo's declared `cmd`, then `health_cmd`, in the train worktree after the train check passes. Namespace `lane-dev-<train_id>` is passed as `LANE_NAMESPACE`; the first backend is a Docker Compose project of that name on the integrator host. A Kubernetes dev namespace on appservice needs train images in a registry and a namespace-scoped ServiceAccount; it is a config change behind the same contract and is not built now (see Deferred). |
| Effect authority | Deploys do not widen authority. Commands come only from `governance/repos.toml` (a protected path for lanes), run only on a train built from reviewed candidates, and get an environment built from `env_allow` plus `LANE_NAMESPACE`, `LANE_TRAIN_ID`, `LANE_TTL_S`; every other variable is stripped, so forge tokens, tracker credentials and kubeconfigs never reach a deploy. Production secrets are never referenced: the deploy uses throwaway example values. |
| TTL and rollback | Every deploy records `expires_at` (`ttl_s`, default 3600). Teardown runs `teardown_cmd` in the repo checkout. A failed deploy or health check tears down at once. `lanectl deploy reap` tears down deploys past `expires_at` or whose train landed or was superseded. There is nothing to roll back: dev deploys never touch production, and `land` is unchanged except for the deploy requirement. |
| Landing | A repo with `deploy` declared lands a train only after a passed `train.deployed` for that train. |

## Contract (planner, protected paths)

New event types, required keys:

- `train.deployed`: `train_id`, `repo`, `namespace`, `passed`, `expires_at` (ISO UTC); optional
  `tail` (last 800 characters of output) and `stage` (`deploy` or `health`) on failure.
- `train.torn_down`: `train_id`, `namespace`, `reason` (`expired`, `landed`, `superseded`,
  `deploy-failed`, `manual`), `passed`.

Runner release (new event types) follows the contract commit.

## Releases

| Release | Outcome |
| --- | --- |
| `s3-repo-config` | `RepoSpec.gate_jobs` and `RepoSpec.deploy` parsed and validated from `repos.toml` |
| `s3-gate-jobs` | gate jobs run after acceptance and are recorded as `job:<name>` gates |
| `s3-train-deploy` | `lanectl deploy <train_id>` with stripped environment, health check, failure teardown; `land` requires a passed deploy where declared |
| `s3-deploy-reap` | `lanectl deploy reap` and `deploy list`; doctor warns on expired live deploys |

Wiring (planner, direct): homelab-analytics `scripts/lane-dev-deploy.sh` and compose override
(unique images and ephemeral host ports per namespace), its `deploy` and `gate_jobs` entries,
a smoke deploy of one train.

## Deferred

- Kubernetes backend on appservice: needs a registry path for train images (push authority
  the lanes do not have today) and a ServiceAccount bound to `lane-dev-*` namespaces only.
  Revisit once a repo's train cannot be checked by the compose backend.

## Exit evidence

Stage 3 exits on per-class agreement at or above the precision bar (unchanged). This plan
supplies the missing lane components; it adds no evidence by itself.
