from pathlib import Path
import json
import shutil
import tempfile
import time
import hashlib
from lanectl import specification as s
from lanectl.config import load_repos, load_lane

r = Path('/tmp/hla-onboarding-native-spec-review-r3-20261115')
packet = Path('/projects/dev/lanectl/docs/evidence/2026-11-15-product-contact/onboarding-planner-lint-r2')
base = 'b2d0fe393ac0971e906cce275e91f45e94422593'
outcome = (packet / 'outcome.md').read_text() + '\n\n' + (packet / 'unit-gate-spec.md').read_text()
bindings = {n: hashlib.sha256((packet / n).read_bytes()).hexdigest() for n in [
    'test_onboarding_expand_acceptance.py', 'onboarding-unit-contract.test.mjs',
    'qualify_unit.py', 'qualify_wiring.py', 'run_wiring_probe.py', 'unit-gate-spec.md']}
outcome += '\nFrozen independent candidate-gate artifacts relative to ' + str(packet) + ':\n' + json.dumps(bindings, indent=2)
proposal = {'outcome': outcome, 'tests': {'tests/test_onboarding_expand_acceptance.py': (packet / 'test_onboarding_expand_acceptance.py').read_text()}}
assert len(json.dumps(proposal).encode()) < s.MAX_RESPONSE_BYTES
prompt = 'Independently adversarially review the first-party frozen acceptance in .lanectl-spec/proposal.json for HLA#2904/sprint580, base b2d0fe393ac0971e906cce275e91f45e94422593. This is a genuine planner correction for revision2, NOT a policy expansion, integrator fix or retry reset. R1 a1 source a5da26bb45c061b5af292d6dfb919867ae40b8f7 was rejected by job:ruff because the frozen planner acceptance had71 style errors. R1 actual browser acceptance16pass is retained, but is not promotion evidence. One actual implementation attempt is consumed; only ONE more attempt is permitted across this outcome. No rejected source is adopted.\n\nRead only public HLA source and public packet /projects/dev/lanectl/docs/evidence/2026-11-15-product-contact/onboarding-planner-lint-r2, including planner-correction.md, correction-proof.json, exact acceptance and six bound gate artifacts, with R1 rejection/frozen packet for comparison. Do not read credentials, private repositories, active worker worktrees or error.log. No product source changes. ca894126 acceptance corrects only split/sorted identical imports and formatting: complete non-import AST, all function bodies and PAGE/SCRIPT/CASES equal old70c99c. Actual target Ruff passes. It is609added+deleted planner lines, hence explicitly not a bounded30line integrator fix. Independently check these claims; AST equality alone does not confer review binding. Review this exact proposal and choose your own verdict.\n\nCanonical already automatically compacts when required account_transactions+subscriptions are fresh; clicking Expand fails. Desired session-only expansion override preserves source-prop transitions, remount reset, Minimise/Dismiss persistence, storage errors, mounted/hydration, strict<7days/future/invalid timestamps, required/optional/empty-source counts, markup/accessibility, role/asof/auth/API. Production-used helper and meaningful Node unit tests plus pytest wrapper count M700; no package/Makefile/dependency/lock changes. Separate from original1597 and exhausted attentionboundary.\n\nChallenge real component subject vs replacement mock, actual post-click waits, exact16case/noskip population, source immutability and owned Next/npmgroup/browser cleanup including Docker launch timeout. Prior ordinary exactbase70c99c had11controlsPASS5postExpandheadingFAIL0errors/skips; corrected ca894126 ordinary base proof is being renewed separately, do not claim it observed until its log exists. npm ci exact candidate package+lock occurs only in owned scratch if Next modules absent. Failure is infrastructure error, never semantic negative. Review raw retained falsifier evidence in previous portability packet if useful. All actual candidate results under newbytes, fullMake55/train/dev/CI remain UNOBSERVED.\n\nThe six artifacts in proposal outcome are mandatory: qualify_unit runs7named tests against actual helper and four closed semantic faults; worker pytest wrapper must itself reject each fault semantically, reject a Node91shim, and cannot merely run node--version. run_wiring_probe must bind green16case baseline completefingerprint before worktree/Next, mutate onlyhelper at exactcandidateSHA, require fiveExpand failures with11controls retained, hash/status invariant and ownedcleanup. Check gate sources for falsepasses. Real-page timestamp/role/past-asof/auth/accessibility and55matchedUbuntuvisualchecks are separate mandatory gates, not proven by component fixture. Final product-intention pass against docs/product/core-household-operating-picture.md and docs/plans/kotona-operating-picture-brief.md.\n\nRead-only. Do not execute acceptance/product/dependency commands, edit source, delegate, push, deploy, change tracker/credentials/grants or permissions. Write ONLY .lanectl-spec/response.json with exactly four keys: verdict(accept or revise), reason(nonempty string), trivial_pass(nonempty concrete attack and whether rejected), checks(nonempty array of nonempty strings). A real issue means revise; never waive a gate. Native Opus supplied initial planning only; firstpartycoordinator is acceptance author. Use actual review model identity from this invocation.\n'
(r / 'request.json').write_text(json.dumps({'model': 'opencode-go/deepseek-v4-pro', 'base_sha': base, 'timeout_s': 1800, 'invocation': 'official installed specification._invoke unchanged; cleanup retention only', 'prompt': prompt, 'proposal': proposal}, indent=2) + '\n')
Original = tempfile.TemporaryDirectory


class Retained(Original):
    def __exit__(self, *args):
        if self.name and Path(self.name).name.startswith('lanectl-spec-'):
            owned = Path(self.name)
            dest = r / 'invocation'
            dest.mkdir(exist_ok=True)
            for child in ['runtime', 'checkout/.lanectl-spec']:
                p = owned / child
                if p.exists():
                    shutil.copytree(p, dest / child, dirs_exist_ok=True)
            (r / 'retention.json').write_text(json.dumps({'complete': True, 'scope': 'runtime and owned response/proposal only; official cleanup still runs'}) + '\n')
        return super().__exit__(*args)


tempfile.TemporaryDirectory = Retained
started = time.monotonic()
try:
    response, usage = s._invoke(load_repos()['homelab-analytics'], load_lane('implement'), base, 'opencode-go/deepseek-v4-pro', prompt, proposal=proposal, timeout_s=1800)
    s._review(response)
    (r / 'actual-return.json').write_text(json.dumps({'response': response, 'usage': usage, 'elapsed_s': round(time.monotonic() - started, 3)}, indent=2) + '\n')
    print(json.dumps({'verdict': response['verdict'], 'complete': True}), flush=True)
except BaseException as e:
    (r / 'error.json').write_text(json.dumps({'type': type(e).__name__, 'message': str(e), 'elapsed_s': round(time.monotonic() - started, 3)}) + '\n')
    raise
