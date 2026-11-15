from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import shutil
import tempfile

from lanectl import specification as spec

out = Path(__file__).resolve().parent
os.environ['LANECTL_HOME'] = '/projects/dev/lanectl'
draft = out / 'qualified-draft'
binding = json.loads((out / 'source-binding.json').read_text())
assert spec.release_digest(draft) == binding['release_digest']
review = spec._review(json.loads((out / 'review.json').read_text()))
native = json.loads((out / 'native-result.json').read_text())
assert review['verdict'] == 'accept' and native['outcome'] == 'done' and native['exit_code'] == 0
assert native['escalation_reason'] is None
baseline = json.loads((out / 'baseline-state.json').read_text())
assert baseline['phase'] == 'terminal' and baseline['lint_problems'] == []
proof = json.loads((out / 'official-base-proof.json').read_text())
assert proof['counts'] == {'passed': 30, 'semantic': 23} and proof['errors'] == proof['skipped'] == 0
assert proof['release_digest'] == binding['release_digest']
evidence = {
    'schema': spec.SCHEMA, 'release_digest': binding['release_digest'], 'review': review,
    'author_model': binding['author_model'], 'reviewer_model': binding['reviewer_model'],
    'intent_digest': binding['outcome_sha256'],
    'recorded_at': datetime.now(timezone.utc).isoformat(), 'lint_problems': [],
    'usage': {'author': {'harness': 'Codex', 'native_provider_invocation': False,
                         'first_party_source_proof_sha256': hashlib.sha256((out / 'final-author-proof.json').read_bytes()).hexdigest(),
                         'cost_usd': None},
              'reviewer': json.loads((out / 'review-usage.json').read_text())},
}
(draft / spec.EVIDENCE_FILE).write_text(json.dumps(evidence, indent=2) + '\n')
assert spec.validate_for_publish(draft) == []
negatives = []
with tempfile.TemporaryDirectory(prefix='hla-priority-binding-') as directory:
    temp = Path(directory) / 'draft'
    shutil.copytree(draft, temp)
    acceptance = temp / 'files/tests/test_overview_priority_gate.py'
    original = acceptance.read_bytes()
    acceptance.write_bytes(original + b'\n# changed frozen bytes\n')
    assert spec.validate_for_publish(temp)
    negatives.append('changed-frozen-acceptance-refused')
    acceptance.write_bytes(original)
    release = temp / 'release.toml'
    original_release = release.read_text()
    release.write_text(original_release.replace('size = "M"', 'size = "S"'))
    assert spec.validate_for_publish(temp)
    negatives.append('changed-release-refused')
    release.write_text(original_release)
    changed = dict(evidence, review=dict(review, verdict='revise'))
    (temp / spec.EVIDENCE_FILE).write_text(json.dumps(changed))
    assert spec.validate_for_publish(temp)
    negatives.append('review-revise-refused')
    (temp / spec.EVIDENCE_FILE).write_text(json.dumps(evidence))
    assert spec.validate_for_publish(temp) == []
(out / 'publication-binding-negative-proof.json').write_text(json.dumps({
    'release_digest': binding['release_digest'], 'forced_refusals': negatives,
    'restored_exact_bytes_pass': True, 'publication': False, 'implementation_attempts': 0,
}, indent=2) + '\n')
print(json.dumps({'release_digest': binding['release_digest'], 'review': 'accept',
                  'base': proof['counts'], 'forced_refusals': negatives}), flush=True)
