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

## A7 source review and live boundary result

A7 `c83fe800fcf7d1adb4adfa4d3b72c958ddca7e35` completed natively in186.9s.
All normal gates passed (worker reported31 frozen acceptance/975 suite tests).
Independent review PASS confirms failed/uncertain stops return false before
terminal polling; exact final module bytes match the immutable reviewed snapshot.
No coordinator implementation fixes were made. The correction is7added/3deleted.
The new failed-stop control fails3/passes1 on A6, so the regression can fail.

Actual installed-service probes on A7 pass24 denied read/write opens across
synthetic credential/state, separate-project, canonical and governance paths,
strip all three synthetic secret environment names, retain checkout writes,
and observe UID1120 with root/nix ownership UID0. The same outside-fence control
opens those paths and sees the environment, returning failure as required. No
secret bytes were read. Evidence and reproducible qualification harness are in
Git; all markers/temporary homes were removed. Full Sovite parity and remaining
repository/lifecycle qualification are running or pending, not yet claimed.

## Released 0.2.5 and actual lifecycle qualification

Client source landed and was tagged/installed as0.2.5 at
`2271ab760b42e56cdaddb36f682b03c1c2251b9d`. The integrated package suite passed
989 tests. The initial train correctly rejected a planner version-lock mismatch;
one2-line spec-gap repair aligned uv.lock, followed by an exact-tip passing
recheck and recorded land plan. No model-error implementation was coordinator-fixed.
Canonical remote main and tag matched; no repository CI workflows/statuses exist.

Full Sovite setup/check through the installed fence passed with exact baseline
population:2797passed/1140skipped (55 complete pytest progress rows; no failures
or errors), source00d29faa. Actual build/setup/check/recheck and historical land
reconstruction passed in an isolated synthetic repository. Root-owned timeout
returned124 with cleanup. KeyboardInterrupt issued one acknowledged stop and
removed the checkout. Injected lost stop acknowledgement retained a named running
orphan; explicit acknowledged manual recovery then cleaned it. Canonical data
remained intact. See the committed lifecycle harness and raw results.

Broader direct-systemd smoke runs found compatibility limits rather than passes:
homelab-analytics raw check lacks the documented DuckDB libstdc++ loader context;
its Makefile route also needs make on the fixed host PATH. Lanectl's full suite
needs a nested user manager unavailable to the dedicated system account
(58failed/931passed). No tests were skipped or weakened. Appservice passes its
complete offline validator when its public origin URL is supplied by setup
(563passed/2skipped/95subtests); an arbitrary source Git config is never forwarded.
The same appservice snapshot also passes in its existing namespace mode. Its local
qualification commit dd64b38b is older than freshly fetched canonical afec5b00;
this result is explicitly snapshot-bound, not proof of latest canonical main.
Homelab's existing namespace command is still running. No global systemd promotion
or Sovite governance change has been made.

Historical qualification also exposed a preexisting destructive cleanup hazard:
_discard attempts rmtree on a canonical recorded checkout after Git refuses it.
Safe interceptors prevented deletion. New public release train-cleanup-boundary
freezes canonical/ancestor/alias failure cases and a real scratch positive case.
This guard must land before closing #2889.

## Configured compatibility and cleanup refinement

HLA's actual configured namespace setup/check passed at canonicalb41e4c9a:
2711passed/1skipped/28deselected,120subtests,544.51s. Appservice's existing
namespace command also passed at recordeddd64b38b. Together with the package's
989-test namespace train and actual Sovite full parity, this provides measured
regression evidence for existing repository modes; it does not qualify every repo
for direct systemd execution or silently switch policy.

Cleanup R1 met its literal four-case acceptance, passed all gates and independent
review. Review refined the broader intended boundary: unmanaged canonical
contents also need protection, historical checks must reconstruct on overlap,
and a completed landing must remain truthful after refused cleanup. R1 is
requeued as planner spec-gap, not accepted or model-fixed. R2 pins its reviewed
artifact and adds six failing safe regressions plus a managed-subtree positive.
No tests/gates/policy or provider caps were weakened.

## Shared-container HOLD and public identity control

Cleanup R2 passed its gates but independent review held source8bcd81a: the
managed container itself could be deleted or yielded writable as a checkout.
R3 freezes eight safe negative cases across inside/outside layouts, aliases
and discard/historical paths. The historical-land positive now also proves
that another safe attempt directory is removed after canonical refusal.
No model-error fix was coordinator-authored.

The published vuoro-client SDK uses the same Bearer header and repo_id envelope
shape as lanectl. With the documented CA input, both the enrolled credential and
a synthetic-invalid control receive HTTP401identity-required from both
work.identity.current and work.public.list-v1. Public discovery is not identity
proof. An initial probe without the CA could not observe authentication and was
repeated with that input restored. No owner mutation, credential substitution or
private-source transmission occurred. Private owner investigation approval is
still pending; catalog advertises no enrollment-management operation.

## Final cleanup candidate and current appservice proof

R3 source dc70775a93b007f7a1e8b144322c6cb0d6e2ce43 passed native gates
and independent review; final runner bytes match the immutable review snapshot.
Its declared managed container and aliases are protected in both layouts, while
individual managed descendants remain supported. The strengthened historical
positive proves safe-attempt cleanup continues after canonical refusal. Source
integration/exact-tip train remains required.

Current appservice afec5b00 passes the complete offline validator in both its
existing namespace and systemd with public origin setup, using a standalone
main snapshot bound to freshly observed origin/main. Its new coherence guard
correctly refuses detached snapshots without the branch fact; no fake CI variables
were supplied and no guard was weakened. This canonical-snapshot proof does not
claim that arbitrary future train proposals have their separate CI context.

## Released cleanup, live cancellation and strict-root correction

Released and installed 0.2.6 at65935f6ee3baec46f1d5ed040195e980e97afe78
includes cleanup R3. Its exact-tip namespace train passed1008 tests and landed
without coordinator implementation repairs. The released lifecycle rerun now
records the canonical checkout as a historical attempt and proves it survives;
build, recheck, historical land, timeout124 and acknowledged/lost-ack cancellation
all pass (live-lifecycle-v026-canonical.json). Actual service cancellation also
observed a live setsid child with PID/start-time binding before stop, then proved
it gone, the unit terminal and checkout removed (live-setsid-dbf142e.json).

Native Claude and Go attempt/usage events are committed in native-auth-events.json.
They demonstrate authenticated native model work; an escalated optional inspection
does not negate the successful authenticated model response. Candidate probes
continue to deny synthetic provider-file path classes without reading secrets.

The expanded actual-host boundary probe includes real /run/user/1000, a sibling
spool tree, state/governance/canonical opens, read-only runtime inputs and receipt
creation denial. Its outside control opens every denied row and sees three fake
secret names. Inside dbf142e, those rows are denied and secrets stripped, but the
public undeclared /etc/issue canary remains readable: the whole probe correctly
fails. This is an explicit missing allow-list finding, not a qualified result
(allowlist-falsifier-dbf142e.json). The strict RootDirectory correction passed
its actual NixOS VM and workstation build; review/integration/apply and renewed
actual-host qualification are pending. Sovite remains environment-only.

Sovite's raw run uses pytest -q in addition to repository quiet configuration,
which suppresses the ordinary final count line. The retained raw output has55
complete progress rows and exit0; counts were derived from2797dots/1140s rather
than invented as an emitted summary. Requalification will preserve this distinction.

Existing public repository commands are being repeated on installed0.2.6. Private
vuoro-cloud has not been executed in this qualification: its configured namespace
command boundary is unchanged, but the shared cleanup path has not been live
exercised there. This is an explicit coverage limitation, not a claimed regression
pass. Private owner investigation approval remains pending.

The corrected live setsid fixture sleeps3600s, records cancellation elapsed and
requires completion under60s (before its independent180s command timeout). The
rerun passed in0.109s; earlier120s-fixture observations are superseded. Boundary
creation probes now record successful open independently of unlink cleanup, so
a cleanup error cannot be misclassified as denied creation. Read-only review
identified these harness gaps and cleared the corrected source before recording
these results. Its template snapshot is labelled configuration, not the executed
instance. The corrected old-host run still fails on the undeclared public canary.

Released0.2.6 full namespace regression passed1008 tests in121.64s with the
user-bus environment supplied. An initial direct invocation omitted both bus
variables and failed58 manager-dependent tests (950passed); this was executor
setup failure, not a product change, and no tests were weakened. Appservice's
configured namespace validator atafec5b00 passed again with installed0.2.6:
563passed/2skipped/95subtests plus all offline validators.

HLA configured namespace rerun on installed0.2.6 also passed atb41e4c9a: 2711 passed, 1 skipped, 28 deselected, 5 warnings, 120 subtests passed in 549.09s (0:09:09). Raw output is in homelab-v026-namespace.json.

## Strict-root source integrated; authenticated apply pending

Canonical gitops PR84 merged at2e77a4eca60a4338aeab00b8f48756916c93d226.
PR and post-main CIrun2205 both passed; the exact committed source used by the
deploy helper also builds successfully. Final reviewed file hashes match
canonical main. The source branch/worktree is retired. See
strict-root-source-integrated.json for the source/build binding.

The new host generation is not yet applied. sudo-n still requires a password;
the operator must switch from /projects/dev/gitops-nixos before actual strict-root
qualification. No failed units remain in either systemd manager. Sovite policy
and #2889 completion remain withheld until the new live proofs pass.

## Current client 0.2.8; strict-host proof still pending

The installed client is now0.2.8 at937b634c16c7b1b1df667041a064a11825e196be,
with runner bytes matched to the independently reviewed retry-routing fix. See
../2026-11-13-product-contact/lanectl-v028-installed.json. The0.2.6 results above
are historical exact-version observations. Neither this client update nor the
merged strict-root source replaces actual-host requalification after the
authenticated switch. The latest host observation still has RootDirectory empty
and User=lanectl-train; no policy promotion or #2889 closeout is claimed.

## Client0.2.9 and publication correction

Client0.2.9 atf9267ea32e481f2a1ecf3f57b07ff0e888e1d0cf is installed after measured idle checks; all61 runtime Python files match reviewed implementation209268d. Focused52/full1038 tests passed, independent source review cleared all findings, and real append-only invalidation of two false draft-publication records preserved every operational projection. This repairs evidence semantics, not the filesystem boundary. Strict host apply and actual strict-generation qualification remain pending; no #2889 closeout or Sovite policy promotion. See ../2026-11-13-product-contact/lanectl-v029-installed.json and publication-invalidation-result.json.

## 2026-11-14: strict host qualified; #2889 complete

The operator applied committed source `2e77a4e`; actual strict-root qualification
and independent audit passed. Sovite's identical source baseline and fenced
check both produced 2,797 passed / 1,140 skipped, counted from retained progress
rows. Boundary, required-input refusal, DNS/TLS, writable checkout, timeout,
cancellation and cleanup controls passed within their documented scope. The
reviewed policy promotion landed as canonical lanectl `ac4c4dd`, selecting
`systemd` for Sovite, and a normal configured canary passed. Served #2889 is done
and reservation498 released. See `../2026-11-14-strict-host/` for raw evidence
and the exact limits; the other repositories keep their qualified configured modes.

A later host observation at configuration `536d12c` retains the identical
qualified fence unit and launcher. The lanectl tick succeeded, its timer is
active, and no failed system/user units remain after the documented cancellation
of an owned read-only API review. The host-generation observation is recorded in
`../2026-11-14-product-contact/current-host-fence-recheck.json`. Whole-system
closure differences remain separately unresolved. Hosted authorized work still
returns identity-required; discovery is not authentication, JSONL remains
authoritative, and the product-count/week-long ladder exits are not established.
