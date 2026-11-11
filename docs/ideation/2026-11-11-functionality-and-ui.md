# Lanectl + Vuoro functionality and operator UI horizon

**Date:** 2026-11-11
**Status:** ideation, not a delivery commitment

## Starting point and product boundary

The first coordinated path now exists: lanectl can register a native run, acquire
and heartbeat a Vuoro-owned lease, append evidence, report an outcome, and confirm
completion with a fresh owner read. Lanectl already owns isolated attempts,
deterministic gates, checked trains, optional dev deployment, landing, recovery,
cost observations, and an append-only event stream. Vuoro composes the existing
work owner and exposes governed operations through a versioned runtime and MCP
surface. Machine-local worktrees and effects remain on the lane host.

That division should remain visible in the product:

- Vuoro's owner operations are authoritative for work identity, readiness,
  claims, leases, evidence chains, and outcome settlement.
- Lanectl is authoritative for lane execution facts, gate receipts, trains,
  deployments, landing receipts, and its event stream.
- A UI may join those facts, cache a read model, and initiate owner operations.
  It must not create a parallel status, lease, decision, or evidence ledger.
- Failure to read an owner is **unknown/unavailable**, not an empty queue. A
  reported outcome is not accepted work; `awaiting-verification` remains pending.

The operator's desired unit is one **request lifecycle**: ready work becomes an
owned lease, one or more attempts, a candidate/train, evidence and an outcome,
then an owner-confirmed terminal result. Release IDs, work IDs, run/lease IDs,
attempt IDs, train IDs, source sessions, and receipts are links on that lifecycle,
not competing task identities.

## Functionality horizon

Value and effort are directional: **H/M/L** relative operator value and **S/M/L**
engineering effort, including owner-contract and qualification work.

### Tier 1: next 1–2 months — make the first flow operable

| Idea | User problem and sketch | Existing dependencies | Risks | Read |
| --- | --- | --- | --- | --- |
| Unified work intake and prioritisation | The operator cannot safely choose across repositories from separate backlog and lane commands. Build a joined ready view using owner-ordered `work.public.list-v1`, repository policy, lane eligibility, capacity, and local release readiness. Show why an item is not runnable; allow filtering and operator deferral without rewriting owner priority. | Vuoro ready/item reads; `lanectl backlog`, `ready`, `lanes`, capacity and release contracts. | “Smart” ranking could silently override owner order. Start with owner order plus explicit, explainable filters. | H/M |
| Claim and lease ergonomics | Claims currently occur inside execution, so ownership and uncertainty are hard to inspect. Add preview, claim-and-run, lease expiry/currentness, heartbeat health, and explicit takeover/refusal explanations. Revalidate immediately before effects. | Run registration, acquire, heartbeat, currentness/report operations; coordination journal and lease guard. | A UI countdown may imply authority it cannot prove. Label last observation and refresh state; never offer a local force-claim. | H/M |
| Evidence and outcome review | Evidence is recorded, but the operator lacks one place to assess gates, checked SHA, deploy health, landing proof, owner report, and owner acceptance. Create a verification queue with a compact evidence summary and drill-down to immutable receipts/references. | Evidence tail/append, outcome report, public item read; lanectl gates, train/deploy/land and `work reconcile`. | Summaries can hide missing links or conflate performer claims with independent verification. Make missing, rejected, stale, and unknown first-class. | H/M |
| Failure triage inbox | Infra stop, gate rejection, lease loss, stale base, owner refusal, uncertain acknowledgement, and verification wait need different actions. Derive reason-coded attention rows from existing events and owner responses, with safe retry/reconcile actions. | `doctor`, `triage`, abandoned-attempt recovery, exact request replay, event contracts. | Heuristic classification could become state. Store no new verdict initially; derive rows and link raw facts. | H/S–M |
| Per-lifecycle time and cost | Current lane/operator accounting is per release and incomplete across waiting/review. Join attempt tokens and estimated USD with wall time in queued, leased, running, gate, verification, and integration phases. Mark estimates and unattributed cost. | Usage hooks, focus, `operator_cost`, event timestamps, run/lease timestamps. | False precision and pricing drift. Preserve units, source, attribution coverage, and estimate labels. | H/M |
| TUI read path and safe actions | Repeated CLI invocations do not provide an operating picture. Deliver the keyboard-first shell described below, beginning with read-only joined views, then owner-backed claim/defer/decline/report actions where advertised. | Existing CLI modules and owner discovery/catalog; served or local lane event authority. | Terminal complexity and accidental effects. Require previews for consequential actions and preserve idempotency keys across uncertain replies. | H/M |

### Tier 2: next quarter — operate an estate, not one host queue

| Idea | User problem and sketch | Existing dependencies | Risks | Read |
| --- | --- | --- | --- | --- |
| Cross-repo trains | A product change may need ordered releases across repositories, but trains are repository-local. Introduce a coordination plan that references existing work/releases and defines dependency order, per-repo checked commits, rollback/stop points, and a final review. Each repository still lands under its own policy and authority. | Work dependencies/readiness, lanectl checked trains/deploys/landing receipts, exact outcome basis. | Distributed atomic landing is unrealistic; partial completion must be normal and recoverable. Avoid calling the plan a transaction. | H/L |
| Multi-operator handoff | Another operator needs to take over without reading chat or guessing whether a lease is live. Produce a handoff snapshot: current owner facts, pending uncertain calls, evidence gaps, next safe actions, and source-session/work links. Acknowledge receipt through an existing owner operation only if the owner supports it. | Continuation delta/work links, request lifecycle and receipts, journal replay. | A snapshot ages immediately and may leak private detail. Include observed-at/checkpoint and bounded references, not transcripts or secrets. | H/M |
| Verification profiles and queue policy | One queue cannot treat a docs change, protected effect, and deploy equally. Define reviewed profiles that name required evidence, independent verifier, freshness, and escalation policy; show profile compliance without manufacturing acceptance. | Gate receipts, evidence kinds, acceptance previews/explanations, work decisions. | Profiles can become a second policy engine. Keep authoritative policy in owners/governance and make UI evaluation explanatory. | H/L |
| Fleet capacity and scheduling advice | Operators need to know which repositories, models, and hosts are saturated before claiming. Provide explainable suggestions based on lane caps, budgets, isolation compatibility, outstanding reservations, and lease health; operator or existing timer initiates execution. | `capacity`, `burn`, routing/allocation policy, lane events and owner ready list. | Drifting into a scheduler or bypassing repository governance. Suggestions do not grant authority or mutate routing. | M/M |
| Notification and subscription rules | Verification waits, imminent expiry, uncertain effects, and blocked trains should reach the right operator. Let users subscribe to derived conditions and deep-link to the same lifecycle in TUI/web. | Stable lifecycle links, owner/event freshness and web view. | Alert storms and notification state becoming work state. Keep acknowledgements personal; resolution comes only from owner facts. | M/M |
| Outcome-quality feedback | Compare accepted/refused outcomes, retries, model route, gate misses, integrator effort, elapsed time, and cost by ruled task class. Feed bounded proposals into existing reviewed learning/governance paths. | Lanectl learning/cost records; owner acceptance and decision links. | Survivorship bias and optimizing for cheap acceptance. Show sample size, missingness, policy revision, and downstream regressions separately. | H/M–L |

### Tier 3: longer-term — a durable multi-repository operating system

| Idea | User problem and sketch | Existing dependencies | Risks | Read |
| --- | --- | --- | --- | --- |
| Portfolio intake and intent decomposition | Operators want to submit an outcome, not manually manufacture every release. An assisted planner proposes repository-scoped work and dependencies, then independent review publishes each governed release. | Lanectl specification lane/draft review; Vuoro work identity/dependencies; cross-repo plan. | Bad decomposition multiplies work and can bypass human intent. Draft-only, provenance-rich, independently reviewed. | H/L |
| Resumable placement across qualified runners | A dead host should not strand work. Expose runner capabilities and recovery evidence so a new qualified runner can acquire/take over through the owner, reconstruct from Git/evidence, and start a new attempt. | Lease takeover/stale-result rejection, continuation, portable contracts, sandbox qualification. | Machine-local state may be unavailable; takeover must never imply worktree migration. Resume from durable artifacts or restart explicitly. | H/L |
| Scenario and dependency control room | For large changes, visualize work, trains, evidence and outcomes as a dependency graph with critical path, aging, and partial-failure recovery. | Stable cross-owner joins and lifecycle read model. | A graph can suggest certainty where joins are stale. Every node carries source and freshness; unknown edges are visible. | M/L |
| Comparative operating economics | Decide where lanes help by task class: total elapsed time, operator minutes, compute/model cost, failure/rework, and accepted outcome—not token price alone. | Reliable lifecycle accounting and sufficient accepted population. | Incentives to under-verify or misattribute shared work. Preserve quality and authority outcomes as separate dimensions. | H/M |
| Policy simulation before rollout | Replay historical public facts against a proposed capacity/routing/verification policy and show counterfactual admissions and costs without claiming predicted outcomes. | Versioned policies, event history, accepted-outcome joins. | Counterfactual outcome claims are weak. Limit results to deterministic decisions and label outcome projections as unsupported. | M/L |

## Operator TUI

### Information architecture

The default home is an attention-oriented queue, not a dashboard of totals:

1. **Ready work** — owner-ready items joined with release/lane eligibility and
   capacity. Owner order is preserved unless the operator visibly sorts it.
2. **Active lanes / leases** — claimed work, heartbeat/currentness observation,
   local process/sandbox state, phase, elapsed time, and expiry.
3. **Needs revalidation** — stale bases, expired evidence, changed owner revision,
   uncertain acknowledgements, lost leases, and incomplete recovery.
4. **Verification queue** — candidates/trains with evidence sufficiency,
   deployment/landing facts, reported outcome, and owner decision.
5. **Deferred** — owner-backed deferrals/declines where supported, plus a clearly
   separate personal hide/snooze preference that changes no work fact.
6. **History** — terminal and superseded lifecycles, searchable by all linked IDs.

Global keys: `1`–`6` switch views, `/` filters, `r` refreshes, `?` opens help,
`Enter` inspects, `[`/`]` changes repository, and `g` opens a lifecycle by ID.
Action keys are contextual: `c` claim, `x` decline, `d` defer, `p` report
performed/outcome, `e` open evidence, `s` jump to the source session/link, and
`R` reconcile/revalidate. Consequential actions open a preview showing the owner
operation, current revision/lease, expected effect, and idempotency state.

```text
┌ Ready work ─ all repos ─ owner order ─ 12:41:08Z ───────────── [?] help ┐
│ FILTER /api_  REPO all  LANE eligible  CAP 2/3                    8 rows │
├──┬──────────────┬─────────────────────────┬───┬──────────┬──────────────┤
│  │ WORK         │ TITLE                   │ P │ RELEASE  │ READINESS    │
│▶ │ analytics#81 │ Repair delayed sources  │ 2 │ hla-src  │ ready        │
│  │ lanectl#2910 │ Evidence review view    │ 3 │ —        │ needs draft  │
│  │ app#902      │ Rotate health contract  │ 4 │ app-hc   │ cap blocked  │
├──┴──────────────┴─────────────────────────┴───┴──────────┴──────────────┤
│ c claim+run  Enter inspect  d defer  x decline  / filter  r refresh     │
└ owner read: current · lane events: rev 1842 · no local ranking applied ─┘
```

```text
┌ Active lanes / leases ──────────────────────────────────────────────────┐
│ WORK/ATTEMPT       PHASE       RUNNER    LEASE OBSERVED      EXPIRES    │
│ analytics#81/a2    gates 3/4   devbox    active 12:40:51Z    00:04:42   │
│ lanectl#2904/a1    worker      devbox    uncertain 12:39:02Z ?          │
│ app#887/a3         deploy      devbox    active 12:40:48Z    00:04:39   │
├ Details: lanectl#2904/a1 ───────────────────────────────────────────────┤
│ local worker: alive · sandbox: active · last heartbeat: transport error │
│ authority: UNKNOWN — effects disabled · exact retry pending             │
│ next safe action: R replay heartbeat; do not start another attempt      │
├─────────────────────────────────────────────────────────────────────────┤
│ Enter inspect  e evidence  s source  R reconcile  q back                │
└ local update 12:41:02Z · owner update unavailable (not an empty result) ┘
```

```text
┌ Verification queue ─────────────────────────────────────────────────────┐
│ WORK              TRAIN   CHECKED SHA  EVIDENCE       OUTCOME           │
│ analytics#81      t-2741  a8139c2      complete       awaiting verify   │
│ app#887           t-2740  c2d44f0      deploy stale   not reported      │
├ Lifecycle: analytics#81 / hla-src / a2 / t-2741 ───────────────────────┤
│ ✓ gates 4/4    ✓ train check @ a8139c2    ✓ dev deploy healthy          │
│ ✓ landed SHA a8139c2                     ✓ evidence append receipt      │
│ ✓ outcome reported: succeeded             … owner decision pending      │
│ Missing: independent owner acceptance (report is not completion)        │
├─────────────────────────────────────────────────────────────────────────┤
│ e evidence  o open receipt  p report outcome  R refresh owner  s source │
└ profile: standard-code@7 · facts observed 12:41:06Z ────────────────────┘
```

```text
┌ Evidence ─ analytics#81/a2 ─────────────────────────────────────────────┐
│ CHAIN  KIND          SOURCE                 FRESHNESS       STATE        │
│  18    Observation   lane gates             commit-bound    valid        │
│  19    Observation   train check a8139c2    commit-bound    valid        │
│  20    Observation   dev deployment         8m remaining    valid        │
│  21    Observation   landing receipt        immutable       valid        │
├ Item 20 ────────────────────────────────────────────────────────────────┤
│ ref: lane://analytics/train/t-2741/deploy                              │
│ summary: health check passed for exact checked commit                   │
│ raw body available locally; owner chain receipt verified                │
├─────────────────────────────────────────────────────────────────────────┤
│ j/k move  Enter details  o open reference  y copy ref  q back           │
└ redaction: public metadata · unavailable bodies remain UNKNOWN ─────────┘
```

### Live updates, accessibility, and offline behavior

Use two independent refresh paths: watch or poll the selected lane event stream,
and poll owner reads/currentness with jitter and backoff. Render a coherent read
snapshot with per-source revision and observation time; do not pretend the join
is atomic. Events can update a row immediately, while authority-sensitive actions
must perform a fresh owner read and compare-and-swap/idempotent write. On reconnect,
resume from the last stream revision/checkpoint and replay exact uncertain requests.

The TUI must work without color, at 80 columns, with configurable high-contrast
themes and reduced motion. Never encode state by color alone: use symbols plus
words. Preserve focus during updates, announce changed row counts in a stable
status line, offer a plain table/JSON mode for screen readers and pipelines, and
make all actions reachable without chords. Times have an absolute UTC toggle.

Offline mode is useful but deliberately limited. It may show the last owner
snapshot with a prominent age, current local events, receipts, and pending exact
replays. It may inspect evidence and prepare a command preview. It must disable
claim, decline, defer, takeover, outcome, and protected-effect actions until owner
authority is freshly checked. “No cached rows” is not “no work.”

## Web UI and one lifecycle across surfaces

The browser should excel where a terminal does not: shareable read-only lifecycle
links, wide dependency and evidence views, side-by-side diffs/receipts, review
comments, notification preferences, and accessible review from a different
device. It is the better verification and handoff surface. The TUI remains better
for rapid queue traversal, local process/sandbox diagnosis, source-session jumps,
and repeated keyboard actions on the execution host.

Both surfaces should call the same versioned query projection and the same owner
operations. A canonical lifecycle URL/locator resolves linked IDs; commands return
that link, and web pages show the equivalent CLI/TUI jump. They share terminology,
reason codes, action previews, source/freshness labels, and idempotency behavior.
Neither surface owns status. Personal web notification acknowledgement and TUI
snooze are presentation preferences, never work resolution. A browser must not
pretend it can inspect host-local bytes: it shows an unavailable/local-only fact
and a safe jump instruction.

## Anti-goals

- No second backlog, scheduler, lease table, evidence store, or decision state in
  lanectl or either UI.
- No “force complete,” “force claim,” or inferred success from a green candidate,
  landed branch tip, report receipt, silence, or elapsed time.
- No distributed transaction fantasy for cross-repo trains; partial progress and
  compensation/recovery must be explicit.
- No raw credential, secret, transcript, or unrestricted runtime-output viewer.
- No browser-based replacement for native lane execution or machine-local effect
  authority.
- No automatic reprioritisation, model/routing changes, gate edits, or production
  promotion hidden behind a convenience action.
- No hosted capability claims beyond operations actually advertised by the public
  catalog and qualified environment.

## Operator decisions and recommendations

1. **Where should the joined read model run?** Options: compute entirely in each
   client; run a local lanectl projection service; or add a shared projection over
   owner APIs. **Recommendation:** start in-process with a reusable query module
   and explicit snapshots; introduce a local service only when multiple local
   clients need efficient subscriptions. Do not create shared state yet.
2. **What does “defer” mean?** Options: mutate an owner-supported work field;
   publish an operator request/decision; or merely snooze locally.
   **Recommendation:** expose owner defer only when advertised and authorized;
   call the local option “snooze” so it cannot be mistaken for coordination.
3. **Should claim be separate from run?** Options: always `claim+run`; allow
   claim-only; or keep claim invisible inside execution. **Recommendation:** make
   `claim+run` the default and claim-only an advanced, time-bounded action with an
   explicit reason, because idle claims reduce throughput and create handoff risk.
4. **Who may verify outcomes?** Options: the performer, any operator, or a policy-
   selected independent principal. **Recommendation:** keep performer reporting
   distinct; require the work owner's existing approval/verification authority,
   with independence dictated by the verification profile.
5. **How broad should the first TUI be?** Options: full mutation surface; read-only
   cockpit; or ready/active/verification plus a few safe actions.
   **Recommendation:** ship the focused three-view slice, read-only first, then
   claim-and-run and exact reconcile. Add decline/defer/outcome only after their
   owner contracts and refusal UX are exercised end to end.
6. **How should cross-repo plans be represented?** Options: a new orchestration
   database; a parent work item with dependencies; or a versioned Git artifact
   referencing owner work. **Recommendation:** begin with a reviewed Git artifact
   plus existing owner work/dependency links. Promote a new owner contract only
   after real plans reveal missing concurrency semantics.

## Proposed first backlog slices

1. **Lifecycle query model (read-only).** Given configured repositories, return a
   normalized row joining owner work/run/lease facts to lanectl release, attempt,
   train, and receipt facts. **Acceptance:** source, revision/checkpoint, and
   `observed_at` accompany every fact group; unavailable owners produce `unknown`,
   never empty; fixtures cover mismatched IDs, stale facts, and partial lifecycles.
2. **Attention reason classifier.** Derive stable reason codes for lease uncertainty,
   revalidation, gate failure, stale deploy, pending verification, and reconcile.
   **Acceptance:** classification is pure over existing facts; each reason links
   its evidence and safe next actions; no event or owner state is added.
3. **TUI shell: Ready, Active, Verification.** Implement the first three views,
   filtering, inspect, evidence drill-down, and source links.
   **Acceptance:** usable at 80×24 and without color; focus remains stable during
   refresh; plain-table mode matches the same query snapshot; all mutations absent.
4. **Fresh refresh and offline contract.** Add independent event/owner refresh,
   checkpoint resume, stale banners, backoff, and offline cached inspection.
   **Acceptance:** simulated owner outage is visibly unavailable; reconnect resumes
   without duplicate rows; authority-sensitive actions remain disabled offline.
5. **Claim-and-run preview.** Invoke existing run registration and lease acquisition,
   then lanectl execution, preserving exact idempotency on uncertainty.
   **Acceptance:** preview names item/repo/lane and observed revision; refusal and
   lost acknowledgement cannot start a second worker; lease loss cancels the worker
   and blocks candidate effects as today.
6. **Evidence bundle and verification view.** Join gate, checked-commit, deploy,
   landing, evidence-chain, outcome-report, and owner-decision facts.
   **Acceptance:** missing/rejected/stale/unknown are distinct; a successful report
   never renders as accepted; references open without copying secrets or raw logs.
7. **Web lifecycle permalink.** Add a read-only shareable view backed by the same
   query schema and reason codes.
   **Acceptance:** every displayed fact has source/freshness; local-only evidence is
   labeled, not fetched; a permalink resolves all known linked IDs and offers the
   corresponding TUI jump command.
8. **Accounting timeline.** Attribute elapsed phases, lane/operator usage, and
   estimated cost to the lifecycle.
   **Acceptance:** totals retain units, price revision, estimate status, and
   attribution coverage; queue/verification time is separate from execution time;
   unknown cost is not rendered as zero.

These slices intentionally establish a trustworthy read and recovery experience
before broad mutation. Once operators have used that surface across several real
repositories, cross-repo trains and multi-operator handoff can be specified from
observed failure and coordination patterns rather than imagined ones.
