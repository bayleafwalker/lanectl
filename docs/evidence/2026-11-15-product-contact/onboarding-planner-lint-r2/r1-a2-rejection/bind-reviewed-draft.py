from pathlib import Path
from datetime import datetime, timezone
import json
import shutil
from lanectl import specification as s
from lanectl.config import load_release

r = Path('/tmp/hla-onboarding-native-spec-review-r3-20261115')
draft = r / 'qualified-draft'
packet = Path('/projects/dev/lanectl/docs/evidence/2026-11-15-product-contact/onboarding-planner-lint-r2')
actual = json.loads((r / 'actual-return.json').read_text())
base = json.loads((r / 'base-population-proof.json').read_text())
request = json.loads((r / 'request.json').read_text())
assert s._review(actual['response'])['verdict'] == 'accept'
assert base['actual_population_qualified'] and base['errors'] == base['skipped'] == 0
assert base['passed'] == 11 and base['failed'] == 5
assert base['release_digest'] == s.release_digest(draft)
rel = load_release(draft)
assert rel.revision == 2 and rel.draft
assert rel.outcome == request['proposal']['outcome'], 'outcome differs from reviewed proposal'
assert rel.base_sha == request['base_sha'], 'base differs from reviewed request'
assert (draft / 'files/tests/test_onboarding_expand_acceptance.py').read_text() == request['proposal']['tests']['tests/test_onboarding_expand_acceptance.py']
evidence = dict(schema=s.SCHEMA, release_digest=s.release_digest(draft),
                review=actual['response'], author_model='gpt-6',
                reviewer_model='opencode-go/deepseek-v4-pro',
                intent_digest=__import__('hashlib').sha256(request['proposal']['outcome'].encode()).hexdigest(),
                recorded_at=datetime.now(timezone.utc).isoformat(), lint_problems=[],
                usage={'author': None, 'reviewer': actual['usage']},
                author_provenance='First-party coordinator adopts mechanical planner correction; native Opus supplied initial planning only.',
                base_population_proof=base,
                prior_attempt_retained='hla-onboarding-expand-a1',
                total_outcome_attempt_limit=2, implementation_attempts_consumed=1,
                further_implementation_attempts_permitted=1,
                candidate_results='UNOBSERVED under revised bytes')
(draft / 'specification.json').write_text(json.dumps(evidence, indent=2) + '\n')
assert s.validate_for_publish(draft) == []
# Force the byte-binding guard to reject a syntactically valid, altered acceptance.
target = draft / 'files/tests/test_onboarding_expand_acceptance.py'
original = target.read_bytes()
try:
    target.write_bytes(original + b'\n# byte-binding negative control\n')
    errors = s.validate_for_publish(draft)
    assert errors and any('changed' in x for x in errors)
finally:
    target.write_bytes(original)
assert s.validate_for_publish(draft) == []
proof = {'positive': 'valid reviewed R2 draft', 'changed_acceptance_rejected': True,
         'restored_acceptance_valid': True, 'release_digest': evidence['release_digest']}
(r / 'binding-falsifier.json').write_text(json.dumps(proof, indent=2) + '\n')
retained = packet / 'native-review'
retained.mkdir(exist_ok=False)
for name in ['run.py','request.json','actual-return.json','retention.json','execution.log','binding-falsifier.json']:
    shutil.copy2(r / name, retained / name)
status = r / 'invocation/runtime/status.json'
shutil.copy2(status, retained / 'native-status.json')
(r / 'bound-draft.json').write_text(json.dumps(proof, indent=2) + '\n')
print(json.dumps(proof))
