# Productive life: the lane ladder (2026-11-10)

**Status:** operator direction, 2026-11-10, after the stage 3 closeout. This plan orders the work
from today's lanectl to a standing system. Rung 1 is built by hand; each later rung is built by
lanes on the rung below it.

## Where lanectl stands (repo at `90e5a7b`, v0.1.27)

| Finding | Evidence |
| --- | --- |
| Productive almost only on itself | 58 of 60 releases target lanectl; the other two are pytest-rootdir fixes (homelab-analytics, sovite). No real homelab-analytics train has gone through `deploy run` and `land`. |
| Capacity is not the constraint | The two waves with closeouts cost about 166k tokens (about $0.70, estimate) against a 3.4M weekly budget. Burn, reservations and decay manage a surplus of about 95%. |
| The planner is the error source and the only source of work | Integrator fix commits: 10 spec-gap, 4 gate-gap, 0 model-error. |
| No routing plurality | `implement` lane: one model at weight 1.0 (`deepseek-v4-pro` is listed, not routed). `retry = "different_model"` and the learning projection have had nothing to compare. |
| No autonomy | `integrator.toml` `autonomous_classes = []`; `lanectl run` is started by hand. |
| A stop condition with no instrument | ADR 0001: "pause the lane if integrator minutes per landed item exceed the cost of doing the work interactively". Lane cost is reported per attempt; planner and integrator cost per landed item is not recorded. |
| Restricted lane has no pool | vuoro-cloud routes to first-party models only, but `allocation.toml` has no Anthropic pool and the interactive reservation is 0.0. |

The precision evidence comes from the easiest class there is: small, greenfield, test-first
modules with a 60-second suite. homelab-analytics has an 11-minute fast suite and only `ruff` as
a per-attempt gate job, so regressions surface at the train. Precision earned on lanectl's own
classes does not transfer, and the stage exits only tick when items flow.

## Target state

The operator writes intents. Everything between an intent and a landed, dev-deployed change is
lane work, including improving the lanes. Standing operator involvement: one planner session a
week, on parked items and ratchet proposals.

Kept out at every rung: autonomous edits to gates, grants or policy (protected paths park for
the operator), and production promotion without an operator Decision.

## The ladder

| Rung | Outcome | Exit | Demote |
| --- | --- | --- | --- |
| 1. Product contact | 10 to 15 homelab-analytics releases through the real path, including `deploy run` and `land`. The only rung built by hand. | About 20 ruled items in a product task class. | Model precision under 50% sends the class back to interactive (existing rule). |
| 2. Lanes write releases | A spec lane turns an intent into a `draft = true` release with acceptance tests, written by a model different from the implementer; the planner publishes. Gates: `lint-release`, fails-on-base for the expected reason, and an adversarial pass that asks whether the test can be passed trivially. | Spec-gap fix rate on lane-written releases no worse than the planner's (today 10 of 14 fixes). | Back to planner-written releases for the class. |
| 3. Plurality | Route a second model at 0.2 to 0.3 now, three or more later (native Codex adapter, Haiku). The learning projection applies weights inside `routing.toml` bounds instead of only suggesting them. | `retry = "different_model"` has fired and changed an outcome. | Weights back to the last reviewed LaneRevision. |
| 4. Standing system | A devbox timer runs `doctor`, `run --max 3` and `deploy reap` without a session. Planner and integrator usage is attributed to items, so the interactive-cost stop condition has a number. The integrator gets landing authority per class and runs headless within `fix_budget_lines`. | One class landed autonomously for a week with no operator-found regression. | Class removed from `autonomous_classes`. |
| 5. Join the substrate | lanectl becomes a Vuoro provider: releases carry sprintctl work ids; workers use the claim, heartbeat, evidence and outcome protocol; the event log moves to the served store; dev deploys move to `lane-dev-*` namespaces on appservice (the deferred stage 3 backend). | One release flows claim to outcome through Vuoro. | JSONL log stays authoritative. |
| 6. Restricted lane off Claude | The local-inference pool becomes a provider for `data_class = "restricted"`, so vuoro-cloud work stops competing with interactive sessions. Until then, add the Anthropic pool to `allocation.toml` before vuoro-cloud runs anything. | A restricted release lands on the local pool. | Restricted work stays interactive. |
| 7. Closure | Recurring `planner_flags` and `gate_flags` become draft releases against lanectl; the investigate lane proposes maintenance for every repo. | The system files a release from its own flags that the operator publishes unchanged. | Flags stay a report. |

Capstone test: replay the backlog against an empty repository. The 60 ordered releases with
frozen acceptance tests are a private curriculum; a model that rebuilds lanectl from them is
qualified, and the specs, not the code, are shown to be the asset.

## This week (order)

1. Rung 1: publish homelab-analytics releases from its sprintctl backlog (pending items include
   the operating-picture, source-remediation, onboarding and freshness tracks) and run the first
   real train through `deploy run` and `land`.
2. Rung 3, first step: route `deepseek-v4-pro` at 0.2 to 0.3 in `implement` (a reviewed
   LaneRevision; the model is already in `external_models`).
3. Rung 4, first steps: the devbox timer, and attribution of planner and integrator usage to
   release ids (the usage hook already records sessions).
4. Rung 6, first step: the Anthropic pool in `allocation.toml`.
5. Rung 2 starts once rung 1 has produced its first ruled product items, so the spec lane is
   measured against product releases, not lanectl's own.

Not now: the Kubernetes deploy backend (rung 5), deeper decision records, burn tuning, and
sprintctl integration beyond carrying a work id on the release.
