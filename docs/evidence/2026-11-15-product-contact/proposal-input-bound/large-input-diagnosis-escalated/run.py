from pathlib import Path
import json, tempfile, shutil, hashlib, time, importlib.metadata
from lanectl import specification as s
from lanectl.config import load_repos,load_lane
r=Path('/tmp/hla-inline-upload-native-r2-diagnosis-20261115')
a=Path('/tmp/hla-inline-upload-acceptance-r2-20261115')
base='b2d0fe393ac0971e906cce275e91f45e94422593'
assert importlib.metadata.version('lanectl')=='0.2.14'
proposal={'outcome':(a/'outcome.md').read_text(),'tests':{'tests/test_hla1587_acceptance.py':(a/'tests/test_hla1587_acceptance.py').read_text()}}
encoded=json.dumps(proposal).encode()
assert len(encoded)==90104 and len(encoded)>s.MAX_RESPONSE_BYTES and len(encoded)<s.MAX_PROPOSAL_BYTES
prompt="""Read-only adversarial review of .lanectl-spec/proposal.json against this public HLA base. First-party Terra authored this R2 acceptance for original HLA1587: upload from a stale row on /sources stays on that page and refreshes that same row, preserving existing backend flow. This draft is already rejected for publication, and R3 is being repaired separately. This call is diagnosis plus a real integration of the newly released trusted-input bound, never acceptance or implementation. Independently assess the exact supplied proposal, challenge trivial passes and impossible candidate expectations, and identify any material issue beyond the four known below. Read source as useful; do not run tests, build, install, invoke providers, read private repositories/credentials or error.log, change source, delegate, push, deploy or edit tracker. Write only .lanectl-spec/response.json.

Known independent blockers: (1) forced-Docker suite unconditionally requires native Chromium for its failure-finalizer control; true Docker-only fallback unproved. (2) browser fixtures A ad_hoc evaluates current and B unconfigured, so original loaded-stale-row outcome untested. R3 must use actual historical successful receipt aged in owned synthetic fixture, real API overdue+old receipt before, same rendered row exact new receipt and sibling isolation after. (3) actual receipt context identity/unreadability checked for201 only, not400/409 although contract covers all receipts; preserve status and truthful categories. (4) npm/build normal exit with surviving child asserts group absent without invoking cleanup; unconditional exact owned cleanup plus real-path orphan falsifier required.

R2 already materially fixes six R1 issues: distinct raw success fixtures, receiptless uncertainty, superseded/missing observation, fixed safe issue templates/strict nested whitelists, ready-but-wrong-bound preflight faults and exact displayed receipt identity, owner-death browser/process-group handling. Check correctness; do not assume claims prove coverage. Actual base final75cases28controls pass47missing-inline-feature fail0errors/skips in native and forced-Docker page modes; those shared failures do not demonstrate candidate behavior. No product candidate/release exists. Original M700/max2 implementation cap and all Make/55visual/architecture/seven specialist/product-intention/train/dev/allCI gates remain unchanged. Native Opus provided earlier planning only; no authority/policy changes. Never approve this known-defective R2 merely because R3 is planned.

Response JSON must have exactly four keys: verdict(accept or revise), reason(nonempty string), trivial_pass(nonempty concrete attack description), checks(nonempty array of nonempty strings). State actual static limits and use revise for material defects. Do not modify the proposal or source. Keep response under64KiB.
"""
(r/'request.json').write_text(json.dumps({'model':'claude-sonnet-5-5','base_sha':base,'proposal_bytes':len(encoded),'proposal_sha256':hashlib.sha256(encoded).hexdigest(),'prompt':prompt,'proposal':proposal},indent=2)+'\n')
Original=tempfile.TemporaryDirectory
class Retained(Original):
 def __exit__(self,*args):
  if self.name and Path(self.name).name.startswith('lanectl-spec-'):
   root=Path(self.name)
   for sub in ['runtime','checkout/.lanectl-spec']:
    source=root/sub
    if source.exists():shutil.copytree(source,r/'invocation'/sub,dirs_exist_ok=True)
  return super().__exit__(*args)
tempfile.TemporaryDirectory=Retained
start=time.monotonic()
try:
 response,usage=s._invoke(load_repos()['homelab-analytics'],load_lane('implement'),base,'claude-sonnet-5-5',prompt,proposal=proposal,timeout_s=900)
 s._review(response)
 proof={'response':response,'usage':usage,'elapsed_s':round(time.monotonic()-start,3),'installed_version':importlib.metadata.version('lanectl'),'proposal_bytes':len(encoded),'official_large_input_call_returned':True,'publication':False,'candidate':'UNOBSERVED'}
 (r/'actual-return.json').write_text(json.dumps(proof,indent=2)+'\n')
 print(json.dumps(proof),flush=True)
except BaseException as e:
 (r/'error.json').write_text(json.dumps({'type':type(e).__name__,'message':str(e),'elapsed_s':round(time.monotonic()-start,3)})+'\n')
 raise
