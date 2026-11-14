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
| Restricted work had no budget | vuoro-cloud routes `claude-sonnet-5-5` through its repo routing table (an earlier version of this plan wrongly said it had no route). Lane Claude attempts were recorded under provider `claude` and admitted unchecked, and nothing bounded their share of the allowance interactive sessions use. Fixed 2026-11-10: `anthropic` provider (allocation rev 9), `lr-claude-provider`, and a `restricted` lane (Claude only, 2/day, run by hand, never by the timer). |

The precision evidence comes from the easiest class there is: small, greenfield, test-first
modules with a 60-second suite. homelab-analytics has an 11-minute fast suite and only `ruff` as
a per-attempt gate job, so regressions surface at the train. Precision earned on lanectl's own
classes does not transfer, and the stage exits only tick when items flow.

## Target state

Implementation update: the 0.2.0 source supplies independently reviewed draft
specifications, recurring-flag intake, bounded headless integration, commit-bound
landing/deploy checks, canonical PR reconciliation, Vuoro lifecycle and served
event streams, qualified allocation/learning and an isolated local provider.
See [the operation guide](../full-stack-operation.md) for opt-in controls and
remaining rollout/product qualification. The workstation timer was observed
enabled and active during this implementation; earlier "not enabled" progress
notes below are historical. No source change establishes the ladder's evidence
clocks or a hosted production rollout.

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
| 5. Join the substrate (plan in the private vuoro-cloud repo, docs/plans/2026-11-10-lanectl-on-vuoro-cloud.md) | lanectl becomes a Vuoro provider: releases carry sprintctl work ids; workers use the claim, heartbeat, evidence and outcome protocol; the event log moves to the served store; dev deploys move to `lane-dev-*` namespaces on appservice (the deferred stage 3 backend). | One release flows claim to outcome through Vuoro. | JSONL log stays authoritative. |
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
4. Rung 6, first step: the Anthropic pool in `allocation.toml`, with an interactive reservation,
   before any first-party model is routed for restricted work.
5. Rung 2 starts once rung 1 has produced its first ruled product items, so the spec lane is
   measured against product releases, not lanectl's own.

Not now: the Kubernetes deploy backend (rung 5), deeper decision records, burn tuning, and
sprintctl integration beyond carrying a work id on the release.

## Progress (2026-11-10)

| Rung | Done | Evidence |
| --- | --- | --- |
| 1 | Two homelab trains through deploy and land | `hla-freshness-recovery` (#1588): train 2693 passed, `deploy run` healthy in 54s, `land` refused before the deploy and tore it down after; homelab PR #79. `hla-domain-freshness` (#1553 parts 1 and 3): train 2704 passed, deployed, landed; homelab PR #80. 2 of about 20 product-api items. |
| 3 | Exit met | implement rev 3 routes deepseek-v4-pro at 0.25; `hla-freshness-recovery-a2` was the first `retry = "different_model"` and changed the outcome (a1 Flash rejected, a2 Pro landed). |
| 4 | Instruments built (v0.1.28) | `lr-usage-focus`, `lr-operator-cost`, `lr-tick`, `lr-otel-export`, `lr-model-windows`: 5 releases, 5 attempts, all first-time gate passes, 1 integrator fix (model-error: a wall-clock test). Timer units in `contrib/systemd/`, not enabled (installing a recurring job needs the operator). v0.1.29: `lr-focus-session` makes focus per Claude session (the operator found the machine-wide focus would misbill concurrent sessions); a1 rejected for editing existing tests (planner error: stale base and an outcome that asked for it), a2 on V4 Pro landed. allocation rev 10 models V4 Pro's own weekly limit. |
| 6 | Anthropic provider added | allocation rev 9: interactive sessions priced at API-equivalent rates; placeholder window, interactive reservation 1.0. |
| 5 | Client activation prepared (0.2.1); live product qualification pending | Runner enrolled; credential-loaded live discovery passes with a product User-Agent. Actual owner-schema verification accepts seven requests and rejects incompatible requests; 782 tests pass. Public-work invocation returned `identity-required` (HTTP 401), escalated to the owner. No repository coordination or recurring activation enabled; the first real product release remains pending and JSONL remains authoritative. |

The 0.2.1 train boundary was exercised with actual repository setup/check commands:
namespace execution passes for homelab-analytics, lanectl and appservice. Sovite's
ownership guards reject user-namespace UID projections, so its explicit
environment-only mode retains normal ownership and matches its full baseline:
2,797 passed, 1,140 skipped. Coordinated work refuses that mode; `doctor` reports
its remaining same-user credential-file exposure when coordination is configured.
An ownership-compatible fenced backend is separate served work `lanectl#2889`.

First operator-cost reading (estimates, corrected): lane work $0.03 per landed release.
Operator cost per landed release is not yet measurable. The Stop hook is installed in the global
`~/.claude/settings.json`, so the $104.88 of interactive usage recorded this week covers every
Claude session on the workstation: agentops ($21.34), appservice ($2.05), a manual hook test
written to the real log ($13.56), and two `/projects/dev` sessions ($43.86 and a partial $24.06)
that are probably lanectl but are not verified. The 66 landed releases also include work from
before the hook existed. An earlier "about 50 times the lane cost" divided all of that by all
66 and was wrong. The number becomes real once sessions set a per-session `lanectl focus`
(`lr-focus-session`) and enough focused releases land; `report` already counts only attributed
usage in `operator_usd/landed`.

Found on the way: implement rev 3 broke the seed fixture's literal weights replace (fixed: the
fixture rewrites the whole line); lane-written deploy tests compared against 13:00 UTC today and
went red after it (fixed). Not yet modelled: V4 Pro's own $15/month limit as a scoped window
(the mechanism now exists; budget in output tokens still to derive).

## Progress (2026-11-14)

The strict-root host fence is applied and qualified; served #2889 is done.
Canonical lanectl `ac4c4dd` promotes only Sovite to its ownership-compatible
`systemd` mode after matching its full baseline. The earlier environment-only
status above is historical. The installed client is0.2.9, including reviewed
retry routing, cleanup and truthful publication evidence corrections.

Product contact continues under HLA1593. Identity PR82 and source-reader PR83
are canonical; PR83 passed the real train/deploy/land path, all four canonical
CI jobs and fresh ancestry verification at merge `30c0caf`. Real default-schema
image smoke checked seven publications and all four complete attention source
groups. The four-kind HTTP adapter and generated contracts are also canonical:
[PR85 delivery evidence](../evidence/2026-11-14-product-contact/api-a7-delivery/canonical-pr85.json)
records merge `b2d0fe3` after the checked train, declared dev HTTP smoke, normal
land and teardown, all four CI jobs and fresh ancestry verification. The dev
smoke matched all eight complete groups against independent SQL, including
slash identifiers and multiple component rows.

The full ranked individual UI acceptance is now a qualified draft over that
canonical API base. Its unchanged-base run reaches real Next and API fixtures
and reports six missing-UI failures with three passing controls and no skips.
Forced skips and incomplete JUnit results are rejected. The
[draft qualification](../evidence/2026-11-14-product-contact/ui-acceptance-draft/qualification.json)
binds the proposal and test bytes. The independent native review has not run:
automatic approval review rejected transmission of this public UI payload to
OpenCode Go DeepSeek V4 Pro, and specific approval is pending. No UI release
has been published or implemented. Meaningful views for all four record kinds,
production ranking and navigation, independent qualification, and complete
UI train/dev/CI delivery remain required.

These prerequisites do not constitute whole HLA1593 completion or the ladder's
about 20 ruled-item exit. Neither source/API prerequisites nor acceptance
authoring are counted here as additional completed product items.

The timer is active and its latest tick succeeded. No week-long autonomous
class exit is claimed. Hosted discovery still does not establish authorized
owner reads; the last credential-loaded probe returned identity-required401.
There is no hosted-flow completion or event-authority switch.
