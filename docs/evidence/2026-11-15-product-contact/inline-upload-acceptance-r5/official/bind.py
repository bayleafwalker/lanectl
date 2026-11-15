from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import shutil
import subprocess

from lanectl import specification as spec
from lanectl.config import load_release, load_repos

root = Path(__file__).resolve().parent
binding = json.loads((root / 'source-binding.json').read_text())
draft = root / 'qualified-draft'
result = json.loads((root / 'actual-return.json').read_text())
base_proof = json.loads((root / 'official-base-proof.json').read_text())
proposal = json.loads((root / 'proposal.json').read_text())
assert result['official_invoke_returned'] and result['binding'] == binding
assert spec._review(result['response'])['verdict'] == 'accept'
assert base_proof['exact_population_qualified'] and base_proof['binding'] == binding
assert base_proof['errors'] == base_proof['skipped'] == 0
assert base_proof['problems'] == [] and base_proof['returncode'] == 1
assert spec.release_digest(draft) == binding['release_digest']
rel = load_release(draft)
assert rel.draft and rel.revision == 1
assert rel.base_sha == binding['base_sha'] and rel.outcome == proposal['outcome']
assert rel.acceptance.exec == ('uv run --no-sync python tests/test_hla1587_acceptance.py',)
for name, source in proposal['tests'].items():
    assert (draft / 'files' / name).read_bytes() == source.encode()
source = Path('/tmp/hla-inline-upload-acceptance-r5-20261115')
assert hashlib.sha256((source / 'tests/test_hla1587_acceptance.py').read_bytes()).hexdigest() == binding['test_sha256']
assert hashlib.sha256((source / 'outcome.md').read_bytes()).hexdigest() == binding['outcome_sha256']
repo = load_repos()['homelab-analytics']
for ref in ['main', 'origin/main']:
    assert subprocess.check_output(['git', '-C', str(repo.path), 'rev-parse', ref], text=True).strip() == binding['base_sha']
evidence = dict(schema=spec.SCHEMA, release_digest=binding['release_digest'],
    review=result['response'], author_model=binding['author_model'],
    reviewer_model=binding['reviewer_model'],
    intent_digest=hashlib.sha256(proposal['outcome'].encode()).hexdigest(),
    recorded_at=datetime.now(timezone.utc).isoformat(), lint_problems=[],
    usage={'author': None, 'reviewer': result['usage']},
    author_provenance='First-party Terra acceptance, explicitly adopted by the root integration owner; native Opus supplied earlier planning only.',
    base_population_proof_sha256=hashlib.sha256((root / 'official-base-proof.json').read_bytes()).hexdigest(),
    base_population={'passed': base_proof['passed'], 'failed': base_proof['failed'], 'errors': 0, 'skipped': 0},
    implementation_attempts_consumed=0, total_outcome_attempt_limit=2,
    candidate_results='UNOBSERVED')
encoded = (json.dumps(evidence, indent=2) + '\n').encode()
assert len(encoded) <= spec.MAX_RESPONSE_BYTES
(draft / 'specification.json').write_bytes(encoded)
assert spec.validate_for_publish(draft) == []
negative_root = root / 'negative-controls'
negative_root.mkdir()
checks = {}
for kind in ['acceptance', 'outcome', 'base', 'review-verdict', 'base-failure']:
    target = negative_root / kind
    shutil.copytree(draft, target)
    if kind == 'acceptance':
        file = target / 'files/tests/test_hla1587_acceptance.py'
        file.write_bytes(file.read_bytes() + b'\n# stale accepted source negative control\n')
    elif kind in ['outcome', 'base']:
        file = target / 'release.toml'
        text = file.read_text()
        if kind == 'outcome':
            old = 'outcome = ' + json.dumps(proposal['outcome'])
            new = 'outcome = ' + json.dumps(proposal['outcome'] + '\nChanged after review.')
        else:
            old = 'base_sha = ' + json.dumps(binding['base_sha'])
            parent = subprocess.check_output(['git', '-C', str(repo.path), 'rev-parse', binding['base_sha'] + '^'], text=True).strip()
            new = 'base_sha = ' + json.dumps(parent)
        assert text.count(old) == 1
        file.write_text(text.replace(old, new, 1))
    else:
        file = target / 'specification.json'
        invalid = json.loads(file.read_text())
        if kind == 'review-verdict':
            invalid['review']['verdict'] = 'revise'
        else:
            invalid['lint_problems'] = ['injected setup failure']
        file.write_text(json.dumps(invalid, indent=2) + '\n')
    problems = spec.validate_for_publish(target)
    assert problems, f'{kind} negative control unexpectedly publishable'
    checks[kind] = problems
assert spec.validate_for_publish(draft) == []
(root / 'binding-falsifiers.json').write_text(json.dumps(dict(
    positive_publish_validation=[], negative_controls=checks,
    original_unchanged=True, release_digest=binding['release_digest'],
    publication=False, candidate='UNOBSERVED'), indent=2) + '\n')
print(json.dumps({'release_digest': binding['release_digest'], 'negative_controls_rejected': list(checks), 'publication': False}), flush=True)
