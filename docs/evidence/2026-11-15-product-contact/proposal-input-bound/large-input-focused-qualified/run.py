from pathlib import Path
import json, tempfile, shutil, hashlib, time, importlib.metadata
from lanectl import specification as s
from lanectl.config import load_repos,load_lane
r=Path('/tmp/hla-inline-upload-native-r3-focused-20261115')
a=Path('/tmp/hla-inline-upload-acceptance-r3-20261115')
base='b2d0fe393ac0971e906cce275e91f45e94422593'
assert importlib.metadata.version('lanectl')=='0.2.14'
proposal={'outcome':(a/'outcome.md').read_text(),'tests':{'tests/test_hla1587_acceptance.py':(a/'tests/test_hla1587_acceptance.py').read_text()}}
encoded=json.dumps(proposal).encode()
assert len(encoded)==114114 and len(encoded)>s.MAX_RESPONSE_BYTES and len(encoded)<s.MAX_PROPOSAL_BYTES
prompt="Read-only focused adversarial review of the genuine supplied HLA1587 R3 proposal in .lanectl-spec/proposal.json. First-party Terra authored it for uploading from a loaded stale /sources row without leaving the page and refreshing that exact row. This is a focused review of native no-JavaScript submit behavior and a real integration check of installed lanectl0.2.14 with114114-byte trusted review input. It is NOT final specification approval, implementation or publication. Full original feature, M700/max2, all Make/55 visual/architecture/specialist/product-intention/train/dev/CI gates remain unchanged. No candidate exists and no implementation attempt is consumed.\n\nIndependently inspect the proposal's no-JS browser scenario and root outcome. The current owner rejects R3 because RP-nojs enumerates forms nested inside rawRows only: valid HTML can place a form elsewhere and associate a visible row submitter via form= ID. Such an actionable row control may submit without preflight while the harness sees zero forms. R4 repair is separate and not in this proposal; do not credit it. Absence of native mutation controls is allowed; requiring attempted>0 is NOT the fix. Does the exact supplied test reject a real external-associated native submitter? Develop a concrete trivial-pass attack and independently assess this known finding. Check whether ordinary browser HTML table reparenting strengthens the concern and what minimal safe acceptance predicate would close it. Do not require candidate behavior unobserved on base. Give your own verdict; accepted final publication is not authorized by this focused call.\n\nThe proposal is large. Read bounded JSON-decoded chunks or search data without executing its Python/browser source. Read public repository source if necessary. Do not execute acceptance/product/dependency commands, install, read credentials/private repositories/error.log, invoke providers, delegate, edit source, push, deploy or change tracker. Write only .lanectl-spec/response.json, preserving proposal bytes. JSON must have exactly four keys: verdict(accept or revise), reason(nonempty string), trivial_pass(nonempty concrete attack), checks(nonempty string array). Explain static limits and keep output under64KiB."
(r/'request.json').write_text(json.dumps({'model':'opencode-go/deepseek-v4-pro','base_sha':base,'proposal_bytes':len(encoded),'proposal_sha256':hashlib.sha256(encoded).hexdigest(),'prompt':prompt,'proposal':proposal},indent=2)+'\n')
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
 response,usage=s._invoke(load_repos()['homelab-analytics'],load_lane('implement'),base,'opencode-go/deepseek-v4-pro',prompt,proposal=proposal,timeout_s=600)
 s._review(response)
 proof={'response':response,'usage':usage,'elapsed_s':round(time.monotonic()-start,3),'installed_version':importlib.metadata.version('lanectl'),'proposal_bytes':len(encoded),'official_large_input_call_returned':True,'publication':False,'candidate':'UNOBSERVED'}
 (r/'actual-return.json').write_text(json.dumps(proof,indent=2)+'\n')
 print(json.dumps(proof),flush=True)
except BaseException as e:
 (r/'error.json').write_text(json.dumps({'type':type(e).__name__,'message':str(e),'elapsed_s':round(time.monotonic()-start,3)})+'\n')
 raise
