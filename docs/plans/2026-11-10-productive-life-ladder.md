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
| 4. Standing system | A devbox timer runs `doctor`, `run --max 3` and `deploy reap` without a session. Planner and integrator usage is attributed to items, so the interactive-cost stop condition has a number. The integrator gets landing authority per class and runs headless within `fix_budget_lines`. | Verify an autonomous landing in ordinary use for one enabled class against the existing class checks and review any operator-found regressions. | Class removed from `autonomous_classes`. |
| 5. Join the substrate (plan in the private vuoro-cloud repo, docs/plans/2026-11-10-lanectl-on-vuoro-cloud.md) | LANECTL becomes a Vuoro Work client, with shared visibility and a public-lane execution pilot on appservice. [Lane history remains a separate architecture decision](../architecture/lane-history-boundary.md). | Verify one real release from claim to outcome through Vuoro. Reconcile the coordination scenarios against owner evidence and verify a scheduled appservice public-lane run, including `lane-dev-*` deployment and cleanup, replacement-runner recovery, and stale-runner refusal. | Keep JSONL authoritative for lane policy and hold additional writers if the policy scope is unqualified. |
| 6. Restricted lane off Claude | The local-inference pool becomes a provider for `data_class = "restricted"`, so vuoro-cloud work stops competing with interactive sessions. Until then, add the Anthropic pool to `allocation.toml` before vuoro-cloud runs anything. | A restricted release lands on the local pool. | Restricted work stays interactive. |
| 7. Closure | Recurring `planner_flags` and `gate_flags` become draft releases against lanectl; the investigate lane proposes maintenance for every repo. | The system files a release from its own flags that the operator publishes unchanged. | Flags stay a report. |

Capstone test: replay the backlog against an empty repository. The 60 ordered releases with
frozen acceptance tests are a private curriculum; a model that rebuilds lanectl from them is
qualified, and the specs, not the code, are shown to be the asset.

## Appservice execution for rung 5

The appservice qualification recorded in Vuoro Cloud work item 2683 uses the
published `lanectl-appservice-candidate` image with pod user namespaces.
Bubblewrap isolates the attempt filesystem. A Longhorn volume preserved state
when the probe moved between workers. The image's coordinated `doctor` check
required a user systemd manager in that candidate. The appservice worker profile
in PR #45 adds a Bubblewrap readiness probe.

On 2026-11-20, the credential-free Job `sovite/lanectl-proc-probe-857d16f`
on `k8s-worker-3` exited 0 with OpenCode 2.3.0 in Bubblewrap's private PID
namespace. It used the candidate digest
`sha256:a23826fee5c500442b0f968ecf442012f5a4509945512ff57d4d9393b6aea3d6`,
`hostUsers: false`, the existing Sovite localhost seccomp profile, a read-only
root, all capabilities dropped and no service-account token. The outer
container used `procMount: Unmasked`, which appservice admitted with a
restricted-policy warning. The probe checked that the outer filesystem marker
was hidden both by its original path and through the inner `/proc/1/root`.
This qualifies OpenCode startup on that pod configuration. The scheduled
coordinator, provider route and end-to-end run require their own evidence.

The synthetic credential Job `sovite/lanectl-credential-probe-bc61b71`
completed on `k8s-worker-2` with the same image digest. A Secret key mounted
read-only using `subPath` appeared as a regular file owned by UID 0 and
GID 11001 with mode 0440. The process ran as UID/GID 11001 with
`fsGroup: 11001` and verified read permission and the read-only mount flag.
This verifies the mount shape used by the gateway credential reader.

Use the appservice image and persistent state for the scheduled pilot. Add an
explicit appservice sandbox profile that hides the coordinator journal,
credential files and environment from the worker and exposes the attempt
checkout plus its declared runtime dependencies. Use the owner heartbeat's
cancellation signal to stop the entire attempt, including descendants. Check
the sandbox during `doctor` and before coordinated admission. Keep one public
pilot policy writer with its own provider budget, and keep the workstation
runner off that policy stream during the pilot.

Qualify with a scheduled public claim and a real accepted outcome. Interrupt
an attempt, resume from the persistent retry journal on a replacement pod,
and verify that the stale runner cannot settle. Capture Kubernetes deployment,
health and cleanup evidence for the train namespace. Exercise these checks on
demand, including credential invisibility and cancellation on lost lease.

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
status above is historical. The installed client is0.2.12, including reviewed
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
binds the proposal and test bytes. The operator approved the public review and
gave standing authorization for OpenCode and Claude reviews and full
implementation within the requested work. Repository data classifications,
protected paths, gates and effect authority still apply.

The actual native DeepSeek V4 Pro review completed with accept and exit 0;
the unchanged official base check and publication validation both returned no
problems. [Review and root disposition](../evidence/2026-11-14-product-contact/ui-spec-review-r1/root-disposition.json)
retain the genuine findings and require additional candidate evidence for
non-null market references and accurate field labels. Guarded publication
occurred at 13:45:08 UTC on November 14, followed by normal Pro attempt
`hla-attention-ui-a1`. Its
[publication and claim receipt](../evidence/2026-11-14-product-contact/ui-spec-review-r1/guarded-publication-and-a1-claim.json)
is a running-attempt snapshot, not implementation or product acceptance.
Meaningful views for all four record kinds, production ranking and navigation,
independent qualification, and complete UI train/dev/CI delivery remain required.

These prerequisites do not constitute whole HLA1593 completion or the ladder's
about 20 ruled-item exit. Neither source/API prerequisites nor acceptance
authoring are counted here as additional completed product items.

The timer is active and its latest tick succeeded. No week-long autonomous
class exit is claimed. There is no hosted-flow completion or event-authority
switch.

### Later November 14 reconciliation

Both full-UI R1 attempts were rejected and the release is parked: Pro timed
out at 2700 seconds with 776 changed lines; Flash also timed out with 728.
The Flash test gates passed, but neither source met the native-success and
M700 requirements. Neither source was adopted and no attempt budget was reset.
The [second rejection](../evidence/2026-11-14-product-contact/ui-a2-rejection/)
preserves that distinction.

A genuine prerequisite now separates the strict whole-ID codec and typed,
authenticated four-kind record reader from the remaining UI. It leaves the
existing backend and all pages unchanged. Its
[independent native acceptance review](../evidence/2026-11-14-product-contact/client-boundary-spec-r1/)
accepted the exact proposal; official base lint and publication validation
returned no problems. Guarded publication at `f44076e` started a normal bounded
Flash attempt, with M700, two attempts and the 2700-second timeout unchanged.
That attempt escalated on a real acceptance-observer defect: Next returned a
lowercase redirect header, while the test had converted case-insensitive HTTP
headers to a plain dictionary. Its 621-line source remains unadopted.
The [minimal two-line repair](../evidence/2026-11-14-product-contact/client-boundary-header-repair/)
passed independent reproduction, retains wrong-status and wrong-destination
falsifiers, and leaves all four-kind behavior unchanged. Fresh native review
accepted revision2; guarded publication at `6049fec` started its normal run.
The 663-line a2 candidate passed normal gates, independent eight-case and
ten-case checks, and seven native specialist reviews. A further actual Node
and browser probe found that its decoder drops a leading Unicode BOM, violating
whole-ID identity. It was rejected and not adopted; full verification was
intentionally stopped, not passed. The
[rejection evidence](../evidence/2026-11-14-product-contact/client-boundary-a2-rejection/disposition.json)
retains that result.

Served `lanectl#2901` repaired the missing ordinary retry-feedback path. Native
review blocked its first patch on legacy replay compatibility; the corrected
source passed 1107 tests and independent rereview, then landed and was installed
as v0.2.11. All 62 runtime files match the tag. The final normal R2 retry, Pro a3,
started at 18:05:20 UTC with the actual BOM observations in its input. The same
criteria, revision and per-revision limits remain. No canonical prerequisite
or whole UI completion is claimed.

Served `lanectl#2902` then repaired a measured namespace completion defect:
stopping an unfinished check could return zero and create a false train pass.
The actual build, recheck and historical-landing red controls failed before the
repair. Native Sonnet review cleared the source; the final suite passed 1120
tests. Released and installed v0.2.12 matches all 62 runtime files. An actual
installed check whose child traps TERM to zero now returns 125 after its exact
unit is stopped, with its completion marker absent. The
[bounded lifecycle evidence](../evidence/2026-11-14-product-contact/namespace-completion/)
retains failed alternatives, startup, timeout, TERM-ignoring process cleanup and
normal output controls. This does not establish arbitrary hostile same-UID
isolation or manager-loss cleanup.

The actual boundary R2 Pro a3 candidate `94ecb4c` has 643 worker changed lines.
Independent frozen CLI 8/8, status/body 10/10, BOM 2/2 and seven native specialist
reviews passed. Its first full Make failed without retained stdout because of
a harness error; a narrow reproduction found Storybook's cache pointed into
read-only canonical dependencies. An owned dependency copy passed all 55 matched
browser checks without lockfile, baseline or tolerance changes. Root's subsequent source read identified uncaught transport failures. An
independent real Next/Node20 probe confirmed that all four kinds propagate the
original synthetic Error object, message and cause. The observing fixture
exposes those fields deliberately; no production disclosure was observed. The
existing outcome already requires sanitized transport errors, so this is
model-error. The final full Make was intentionally stopped, not passed; the
installed v0.2.12 supervisor returned 125 with no inner completion marker. Exact
owned browser, unit and qualification checkout cleanup passed.

A3 is parked and R2's two-attempt budget is exhausted. The
[rejection archive](../evidence/2026-11-14-product-contact/client-boundary-a3-rejection/)
keeps all passing checks, the raw counterexample and redirect controls, partial
verification and source. No invalid source was adopted. Missing test coverage
does not turn the clear requirement into a spec-gap or authorize a new revision.
The permitted integrator fix classes are spec-gap and gate-gap, not model-error.
Normal train, dev and canonical delivery remain pending; no prerequisite or
whole UI completion is claimed.

The [portable repaired full-UI observer](../evidence/2026-11-14-product-contact/ui-portable-observer-preparation/)
is preparation only. Its base run has six missing-feature failures, three
passing controls and no skips. It still needs revalidation and fresh native
review on the eventual canonical prerequisite head. All four record views,
ranking, complete facts, independent qualification and built-product delivery
remain required. These steps add no completed product-item count.

Specific approved owner diagnosis established that the enrolled runner's
issuer is `https://api.vuoro.cloud`. The earlier direct shared-service 401 is
historical evidence from the wrong destination. An actual read at the issuer
authenticated, correlated and returned an empty ready list. Installed lanectl 0.2.9
reported that result as unknown because its catalog-schema validator rejected
valid literal constraints. Served `lanectl#2900` tracked the repair. The first
fix passed its suite but independent review and actual catalog inspection
found broader compatibility gaps. Revised source was independently cleared,
passed 1097 tests, landed and released as v0.2.10. All 62 installed runtime
files match that release, and the installed readback returned observed with
zero ready items. A synthetic invalid runner was refused with HTTP 401; see
[installed evidence](../evidence/2026-11-14-product-contact/owner-catalog-compatibility/rollout.json). No claim, grant, profile, deployment
or event-authority change was made.


### 14November source composition and independent product packet

VuoroPR325 landed the optional lanectl0.2.12/Python3.13composition after13CIchecks,
native independent review,3869source tests and11bounded exact-image probes.
[Adoption proof](../evidence/2026-11-14-product-contact/released-wheel-and-hosted-prerequisites/vuoro-source-adoption.json)
records canonical ancestry and identical checked tree. Vuoro2903 is accepted;
production hosting, persistence and JSONL authority remain unchanged.

Independent HLA2904 addresses completed-core onboarding Expand; automatic
collapse already exists on canonicalb2. The original1597unitcriterion remains.
Its [frozen preparation packet](../evidence/2026-11-14-product-contact/onboarding-expand-preparation/README.md)
passed independent gate review and actual base proof11controls/5semantic failures,
no skips/errors. Native adversarial review and all candidate/product delivery
proof remain pending; this adds no completed product item or boundary retry.


### 14November base evidence and ordinary onboarding implementation

Actual fresh-clone qualification exposed16setuperrors that the old base classifier
accepted as expected. Lanectl2905 fixed setup AssertionError phase handling,
released and installed0.2.13 after1127tests and independent native review;62runtime
files and all3public assets were byte-verified. [Proof](../evidence/2026-11-14-product-contact/base-lint-setup-phase/README.md)
retains real red/publication controls and conservative classification limits.

The separately repaired onboarding acceptance received renewed nativeGoProaccept.
Ordinary base and publication runs each show11controlsPASS/5semanticExpandFAIL,
no errors or skips. HLA2904 releaseR1 was guarded-published and its first native
Pro attempt completed, as qualified below. [Packet](../evidence/2026-11-14-product-contact/onboarding-portability-r2/README.md).
PolicyPR7 remains a prepared standing model-error proposal; canonicalauthorityv1
and empty autonomous classes are unchanged. This adds no evidence-clock exit.

### 15 November planner acceptance lint correction

Onboarding a1 completed natively at source `a5da26b`; normal diff, base-negative
and frozen browser gates passed, but Ruff rejected 71 style errors in the
planner-owned frozen acceptance. The attempt remains rejected and R1 is now
parked so the enabled tick cannot dispatch the unchanged broken packet. Source,
native completion, original release and rejection history are
[preserved](../evidence/2026-11-15-product-contact/onboarding-planner-lint-r2/README.md).

The planner correction passes target Ruff, preserves all non-import AST and
normalized import aliases, and reproduces exactly 11 passing base controls and
five semantic Expand failures with no errors/skips. At 609 added-plus-deleted
planner lines it exceeds the integrator allowance and requires a genuine R2
with new byte-bound independent review and guarded publication. Native review
accepted the corrected bytes, but the live admission preflight refused: the tick
had already admitted Flash a2 overnight. A2 timed out at2700s and was rejected;
both total attempts are consumed. Root had relied on the stale handoff's count
when preparing R2 and has corrected that error in Git and served work state.
No R2 was published and no new worker launched. Canonical R1 is unchanged and
parked; the prepared scratch specification is explicitly invalidated. A new
revision must not be used to obtain a third attempt. No attempt promotion or
policy activation occurred.

An independent diagnostic audit of preserved a1 passed the seven helper contract
tests, four helper faults, actual worker wrapper and its four semantic faults
and Node-execution negative control. That does not qualify a new candidate.
Full Make/55 visuals, real-page behavior, native specialist review, train/dev,
PR/CI and canonical adoption remain required before product acceptance.

The original intended backlog was then read from the served store. HLA1592's
four-kind horizon still needs explicit contracts for approval deadlines and
reader-safe due exports; dates cannot be invented from creation time or expected
source arrival. The independent existing HLA1587 source-row upload item is now
active under reservation505. [Discovery and planning evidence](../evidence/2026-11-15-product-contact/inline-upload-plan/README.md)
retains its actual six-test backend baseline and the first native Opus plan.
The first draft needed correction because configured ingestion already accepts
XLSX and JSON even when detection supplies no matching candidate. Native follow-up
completed successfully; the owner disposition also corrects unsafe upstream
messages and unsupported inference from latest-run snapshots. A private
production-Next/real-API bootstrap exercised existing supported-format and role
controls; its [partial readiness archive](../evidence/2026-11-15-product-contact/inline-upload-bootstrap/README.md)
preserves all measured limits. Consolidated independent acceptance is still being
qualified on the unchanged base before any implementation release. No additional
onboarding attempt was authorized. A fresh live-ledger check found zero existing
records for the proposed source-upload release; this is preparation, not admission.

Both attempted served `sprintctl render` commands were refused as operation
unavailable. No local database fallback was used; served work remains
authoritative and the measured changes are retained in Git. This is a snapshot
tooling gap, not product completion or a reason to widen authority.


## Progress (2026-11-15)

Installed lanectl 0.2.14 closes served #2906 with accepted decision 485 and reservation 506 released. Trusted review input has an independent 256 KiB bound before dispatch; model output stays 64 KiB and intent 16 KiB. All 1,140 tests and independent native source review passed. Two clean exact-tag offline wheels, 62 runtime files, public asset readbacks and installed bytes match. An actual official native review of a 114,114-byte proposal completed with revise for a real acceptance gap. That qualifies input handling. [Closeout](../evidence/2026-11-15-product-contact/proposal-input-bound/CLOSEOUT.json).

Original HLA #1587 inline stale-row upload is independently specified over canonical API b2d0fe3. The first-party Terra R5 acceptance has 92 named cases: 35 controls pass and 57 fail for missing inline routes, row controls or availability explanations, with no errors or skips. Native and genuinely native-unavailable Docker runs, official base qualification and guarded publication recheck match case for case. Independent static and full native GoPro reviews accepted the frozen bytes. [Preparation evidence](../evidence/2026-11-15-product-contact/inline-upload-acceptance-r5/README.md).

Release `hla-source-row-upload` R1 was guarded-published and pushed at `03d9614`, then its first native Go Flash implementation was claimed at 11:26 UTC. At the 11:39 UTC ledger reading, a1 remained active with one actual claim and no finished result. The timer was restored and enabled. This is a timestamped observation: read the live ledger before deciding any retry or revision. Maximum two actual implementation attempts and M700 remain unchanged; planner repairs did not consume or renew that budget. Candidate green, all delivery gates, train/dev health, CI and canonical feature adoption remain unobserved.

Onboarding #2904 R1 exhausted both Pro and Flash attempts; corrected planning did not authorize another publication or attempt. Attention-boundary R2 remains exhausted. Model-error repair permission is only [draft PR #7](https://github.com/bayleafwalker/lanectl/pull/7), with canonical authority still revision 1, spec-gap/gate-gap classes, cumulative 30 lines and no autonomous classes. No source or preparation establishes an autonomous week, hosted claim-to-outcome, restricted local-pool landing or unchanged self-filed release exit.


The first inline-upload model later timed out after 2,700.2 seconds. Its 685-line source passed all five recorded gates, but independent immutable-source review found stale row cells, lost receipt qualifications, wrong-preview relabeling, catalog reads that fail open and superficial helper tests. It remains rejected. The integrator recorded these original-outcome findings before the remaining normal R1 retry. The second claim started at 12:26 UTC on Go Pro with that bounded feedback, without changing the specification, M700, two-attempt cap or policy. [First-result evidence](../evidence/2026-11-15-product-contact/inline-upload-a1-rejected/REVIEW.md).

An independent local-route prerequisite is now observed: OpenCode 2.2.6 and installed lanectl 0.2.14 completed a real `local/worker-fast` file read/write probe in 27.94 seconds. Four observed relay requests went to the explicit loopback model and returned 200. A held inference lock refused native dispatch with exit 3 and no model request, and the owned lock released. This is operational wiring evidence, not private-product quality, GPU attestation, a routing promotion or the restricted-release landing exit. [Local readiness](../evidence/2026-11-15-local-route-readiness/README.md).

### November 15 inline-upload disposition and next product contact

HLA1587 R1 exhausted both native implementation attempts and is parked. Flash
timed out at2700.2s with685changed lines; its frozen gates passed but source review
found original-outcome defects. Pro also timed out at2700.2s and changed942lines,
exceedingM700 by242. Its diff-policy and fail-on-base gates failed; frozen
acceptance and Ruff passed. Neither source was adopted, and no attempt budget
was reset. [Final source and ruling](../evidence/2026-11-15-product-contact/inline-upload-a2-rejected/README.md)
retain the distinction, unchanged preserved tests and independent bundle proof.
The same-row inline-upload outcome and all delivery gates remain incomplete.

The next separate original pending item is HLA1590: one card per active domain,
with a real headline metric, trend and its top attention item, plus a truthful
empty state. Served reservation507 owned native read-only planning over canonical
b2d0fe3. This is planning only: no release, implementation or product completion.
Missing domain/metric/ranking contracts must be resolved from actual reporting
semantics; freshness-only cards or global attention do not satisfy the outcome.
Policy PR7 remains a reviewed preparation-only draft; canonical authority remains
revision1 with empty autonomous classes. No local restricted/hosted/clock exit
is established.

Native domain-card planning has now completed with actual Opus5.5 exit0 in
553.063s. The [planning disposition](../evidence/2026-11-15-product-contact/domain-cards-planning/plan.md)
keeps the full outcome but is not implementation-ready: currency-safe reporting,
populated homelab history/attention and priority require
contracts or genuine prerequisites. The native1,450–1,750-line estimate is
unmeasured and includes no additional homelab contracts; no M700 waiver or
unsupported-facet substitute was adopted. Reservation507 is released. No release
or implementation attempt has started for1590.

The operator resolved active membership on November15: loaded capability packs
that own sources, currently Finance, Utilities and Homelab. No-data active
domains remain enumerable. The [recorded decision](../evidence/2026-11-15-product-contact/domain-cards-planning/owner-decision-active-domains.json)
settles membership; currency-safe reports and populated-homelab trend/attention,
priority consistency and complete-outcome feasibility remain prerequisites.


### November 15 existing-rule unit coverage accepted

HLA1597 is accepted by served decision486, reservation508 released. The existing
automatic core-source collapse rule now has meaningful real-component coverage
from two new test files,159addedlines underS250, with no product changes.
[PR86](https://github.com/bayleafwalker/homelab-analytics/pull/86) merged as
82dbd9477029d6fda7df67edc617f45a1a4ceb59 after full local Make and all four CI
jobs passed. All55visual checks kept their existing baselines. Ten unit cases
pass; disabling only auto-collapse causes exactly three semantic failures and
seven controls pass. Four independent Python wrapper failure probes also reject.
[Source-bound closeout](../evidence/2026-11-15-product-contact/onboarding-auto-collapse-unit/closeout.json)
retains actual two native Sonnet implementations, eleven read-only reviews,
original incomplete findings and local runtime/invocation failures. This is
existing-rule coverage, with no new lanectl release or ruled product-class count.
Exhausted Expand2904, upload1587 and attention1593 outcomes remain unadopted.

At15:41UTC, bayleaf's user manager reported no failed units; lanectl-tick.timer
was active/waiting, and its17:29:52EET tick exited0. The only failed system unit
was home-manager-bayleaf.service, the existing concurrent activation conflict.
No broad reset or unrelated restart was performed.


### November 15 public optional-image publication qualified

Vuoro #2907 is accepted by served decision 487, with reservation 509 released.
[PR #326](https://github.com/bayleafwalker/vuoro/pull/326) merged as
784c0192 after all 14 checks passed, including the new optional-image build,
PostgreSQL workspace checks and production contract toolchain. The existing
default publisher remained byte-identical.

The actual [publication run](https://github.com/bayleafwalker/vuoro/actions/runs/43738166657)
built the explicit Python 3.13 optional composition and exposed separate lane
aliases only after exact-digest checks passed. Independent registry readback
then verified both aliases, source/workflow provenance and the pulled image's
installed closure: Python 3.13.18, lanectl 0.2.12 and the reviewed work, audit,
knowledge and shared pins. The public index digest is
`sha256:15f84e1c7456191bf769f8907938f0f38da9875124e4434bdba2694b8141ec82`.
[Source-bound closeout](../evidence/2026-11-15-public-lane-image-publication/CLOSEOUT.json)
retains the receipt, readbacks, source reviews and local verification, including
the earlier unconfigured full-suite failure.

This closes the public artifact-publication prerequisite. It proves no hosted
deployment, tenant migration, lane persistence/restore or event-authority
cutover. It adds no ruled product-class result or evidence-clock exit.


### November 15 owner recovery tools released

LANECTL2910 is accepted by served decision489. PR8 landed exact source `d64fb00` after actual Ubuntu CI passed all1,217 tests with zero failures, errors or skips and real systemd isolation, timeout and stop preflights. Version0.2.15 is published and installed: two clean offline wheels are byte-identical, all63 runtime files match source, three release asset readbacks match, and isolated/external installed-wheel CLI recovery proofs pass. The first Ubuntu run's two fake-provider shell failures and actual dash red/green correction are retained with unchanged assertions. [Release closeout](../evidence/2026-11-15-stream-recovery/release-v0.2.15/README.md).

This closes the local owner-tool prerequisite. Exact-image service recovery in disposable storage remains the next integration proof; hosted volume recovery, backup custody, gateway flow and authority cutover remain unqualified.

### November 15 overview priority review failure

HLA2908 used both original attempts. A1 timed out after its681-line source passed all five gates. A2 completed with651lines and passed all five gates, all53 frozen acceptance cases, full Make and55 unchanged UI checks. Seven specialist reviews plus actual source execution then exposed a valid-row contract violation: Python orders fullwidth U+FF21 before emoji U+1F600, while the browser helper reverses them. The literal route-size blocker also remains unresolved. Raw briefing coercion failures were reproduced only through the data provider seam; ordinary typed INTEGER publication reachability is not claimed.

The integrator parked A2, served2908 is blocked, and verification reservation510 is released. Both source bundles were independently restored from base-only repositories and retained with original passing checks, review findings and factual counterexamples. [Complete closeout](../evidence/2026-11-15-product-contact/overview-priority-closeout/README.md). No repair, third attempt, gate/spec/budget reset, train or adoption occurred. Canonical integrator revision1 grants no model-error repair authority; PR7 remains an unactivated draft. Original1590/1593 outcomes remain incomplete.
