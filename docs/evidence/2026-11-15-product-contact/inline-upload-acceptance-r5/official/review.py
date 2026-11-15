from pathlib import Path
import hashlib
import importlib.metadata
import json
import shutil
import tempfile
import time

from lanectl import specification as spec
from lanectl.config import load_lane, load_repos

root = Path(__file__).resolve().parent
binding = json.loads((root / 'source-binding.json').read_text())
proposal_bytes = (root / 'proposal.json').read_bytes()
assert hashlib.sha256(proposal_bytes).hexdigest() == binding['proposal_sha256']
assert importlib.metadata.version('lanectl') == '0.2.14'
proposal = json.loads(proposal_bytes)
prompt = '''Independently adversarially review .lanectl-spec/proposal.json against this public HLA base b2d0fe393ac0971e906cce275e91f45e94422593. The original HLA1587 outcome is upload from a loaded stale source row on /sources without navigating away, refreshing that exact row and preserving the existing backend flow. First-party Terra authored the supplied R5 acceptance; native Opus supplied earlier planning only. No candidate or release is published. Live outcome history is measured as zero attempts, with a fixed maximum of two across the entire outcome and M700 added+deleted worker lines including tests/docs. No policy, retry, gate, auth, dependency, backend or OpenAPI expansion is permitted.

Read the exact proposal and actual public source. The proposal is large: inspect the entire supplied test using bounded read-only JSON decoding/chunks, never executing its source or inferring unread tails. Challenge impossible candidate expectations, false passes, disconnected provenance, privacy/role/CSRF/pinned source identity, preflight cancellation and late responses, raw safe-template handling, receiptless uncertainty, error-receipt source context, observation vs attribution, exact displayed/BFF/backend receipt identity, real historically loaded overdue row precondition, sibling isolation, no-JS nonmutation and lifecycle cleanup in actual native or genuinely Docker-only environments. Tests have base-positive controls and expected missing-feature negatives; shared missing-feature failures are not candidate proof. Critically assess the binding, fixtures, browser subject, startup failures and named populations. Reject material gaps; no pressure to accept.

R1 through R4 were rejected before any implementation. R5 is intended to repair earlier duplicated success bytes, certainty without receipts, missing observation semantics, diagnostic disclosure, wrong-bound preview faults, stale fixture omission, native-only Docker guard, error-receipt identity, build descendant cleanup, optional observation mismatch, cancellation false rejection and disconnected displayed/backend receipt IDs. R5 also repairs actual form ownership/implicit no-JS submission, visible discriminating current-file preview facts, flexible count-label order and coherent shared-format/account ambiguity wording; independently challenge these predicates with legitimate alternative prose and absent/irrelevant information. Independently verify actual code rather than relying on this claim. Safe no-JS absence of native inline controls is allowed, provided a real seeded row is observed and no mutation occurs. Preserve actual receipts under identity mismatch; never claim matched source, current freshness or publication without evidence. A legacy route rewrite control is only base-positive harness evidence; separate real inline faults must test candidate behavior. Self-CLI population enforcement is deliberately scoped, with ordinary JUnit externally audited. Do not require a global plugin affecting whole-repository collection.

All original full Make/55 unchanged visual/architecture/seven native specialist/product-intention/train/dev health/all CI/canonical adoption gates remain required and unobserved for any future candidate. No cut coverage to fit M700; no revision resets attempts.

Read-only. Do not execute acceptance/product/dependency commands, read credentials/private repositories/error.log, delegate, invoke other models, edit source, publish, push, deploy or change tracker. Write ONLY .lanectl-spec/response.json with exactly four keys: verdict(accept or revise), reason(nonempty string), trivial_pass(nonempty concrete attack and whether rejected), checks(nonempty string array). Never modify proposal bytes. Use revise for real defects and state static limitations. The response must remain below64KiB.
'''
(root / 'review-request.json').write_text(json.dumps({
    'binding': binding, 'model': binding['reviewer_model'], 'prompt': prompt,
    'timeout_s': 1800, 'official_invoke': True, 'publication': False}, indent=2) + '\n')
Original = tempfile.TemporaryDirectory

class Retained(Original):
    def __exit__(self, *args):
        if self.name and Path(self.name).name.startswith('lanectl-spec-'):
            owned = Path(self.name)
            for sub in ['runtime', 'checkout/.lanectl-spec']:
                path = owned / sub
                if path.exists():
                    shutil.copytree(path, root / 'invocation' / sub, dirs_exist_ok=True)
        return super().__exit__(*args)

tempfile.TemporaryDirectory = Retained
started = time.monotonic()
try:
    response, usage = spec._invoke(load_repos()['homelab-analytics'],
        load_lane('implement'), binding['base_sha'], binding['reviewer_model'],
        prompt, proposal=proposal, timeout_s=1800)
    spec._review(response)
    result = dict(response=response, usage=usage,
        elapsed_s=round(time.monotonic() - started, 3),
        binding=binding, official_invoke_returned=True, publication=False,
        candidate='UNOBSERVED')
    (root / 'actual-return.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)
except BaseException as error:
    (root / 'error.json').write_text(json.dumps({'type': type(error).__name__,
        'message': str(error), 'elapsed_s': round(time.monotonic() - started, 3)}) + '\n')
    raise
