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
