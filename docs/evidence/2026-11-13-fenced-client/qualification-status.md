# Fenced client qualification — 2026-11-13

A4 `2cfa660fdce4a33303d67e9cfaeb0160c6410002` is **held and requeued**.
The actual native trace ran ten frozen checks (0.44s); an optional inspection
command denial conservatively escalated the attempt. The integrator independently
measured 83 changed implementation lines, ran the frozen old-base control
(3 failed / 7 passed), corrected acceptance (10 passed), and the full-suite gate
inside the normal credential-isolating namespace. All those gates passed. The
original escalated outcome is preserved; no approval or landing was recorded.

Independent native Claude review nevertheless found premature terminal handling
for a queued `start --no-block` (B1), plus missing linked-worktree staging evidence
(B2). The new frozen pending-start tests safely reproduce both lifecycle cases
on A4, while both real linked-worktree forms already stage correctly:
**2 failed / 2 passed**. Revision 6 targets A4 for a bounded lifecycle correction,
routed through the existing public implementation lane. Neither provider budgets
nor lane caps changed. Tests and protected paths remain immutable to the worker.

The A4 worker took 39.1s and reported $0.1755437 API-equivalent adapter usage.
Review cost and coordinator effort were not measured. Earlier A1/A2/A3 repairs
remain historical rejections; passing gates did not erase model errors.

Host fence source is merged in canonical gitops-nixos PR 83 at
`dbf142e2636d0397c7aeb5cacad3b4b1adfe2df4`; independent review, the NixOS VM,
workstation build and CI passed. Authenticated workstation apply remains pending:
`lanectl-train@qualification.service` is not found and the account is absent.
Fresh ordinary Sovite baseline `00d29faa` is 2,797 passed / 1,140 skipped.
No real fenced parity, cross-repository qualification or runtime deployment is
claimed. Sovite's current isolation policy is unchanged.

Hosted discovery is public: both an invalid synthetic credential and the enrolled
opaque runner credential can discover, but `work.public.list-v1` returns HTTP 401
`identity-required` for both. Discovery does not establish authentication. No
claim or work mutation was attempted. The public operation requires `work:read`
and is repository scoped; its catalog supplies no authentication metadata.
The private owner investigation has not run because automatic approval review
rejected sending private source to Anthropic without specific approval.

This committed evidence is cross-host-replicated Git source. Scratch logs and
qualification harnesses in `/tmp` are session-local. Served #2889 remains active.

## Revision 7 follow-up

The planner interrupted R6/A5 to bound an old missing-receipt fixture and
strengthen its stop-before-cleanup assertion. The native outcome is `failed`,
exit 130, not completed work. A partial 31-line artifact was captured at
`37a052c45e00679f04208b905a98b9f35cb8ef23`; its ordinary gates then passed,
but the new 24-second queued-start control fails because its short grace still
truncates the overall deadline (1 failed / 3 passed). The original held A4
fails both lifecycle cases (2 failed / 2 passed); linked-worktree staging passes
on both. Neither artifact is accepted.

R7 freezes the existing lifecycle test file with a one-second deadline only
for the forged/missing-receipt case and requires an exact-unit stop when the
root receipt is absent. This is a planner test-specification repair; no worker
is authorized to edit tests. A legitimately queued start may last longer than
the short receipt grace and must use the overall deadline. Existing lane and
provider caps remain unchanged.

## Installed host and final cancellation correction

The operator applied committed host source dbf142e. Independent probes now observe
UID/GID1120 nologin, coordinator0700 spool, root0755 receipt directory, loaded
lanectl-train template, and the expected system generation (host-installed.json).
Both system and user managers report zero failed units. Earlier notification noise
came from four temporary failed qualification probes and their recovery messages;
the recurring lanectl tick is healthy. Future temporary units use automatic
collection with results retained in artifacts/events.

R7/A6 source 49f0c4b matches the independent PASS snapshot exactly and all lane
gates passed (native worker reported27 acceptance/971 suite tests). However, the
integrator forced the review's failed-stop advisory into its failure case and
held landing: refused, timed-out and unavailable stops all returned terminal=True
from a bare inactive reading. The synthetic root control is3failed/1passed.
A queued start is not proven cancelled without a successful stop acknowledgement.
R8 freezes those cases and routes the tiny correction through the existing public
implementation lane. A6 remains requeued, not landed. No gate waiver or cap change.
