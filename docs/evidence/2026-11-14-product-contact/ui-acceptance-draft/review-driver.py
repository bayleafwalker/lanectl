"""Review only the final hash-bound full UI acceptance; never implement it."""
import hashlib
import json
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from lanectl import specification as spec
from lanectl.config import load_lane, load_repos
from lanectl_persistent_spec_review import invoke

root = Path('/projects/dev/lanectl')
packet = root / 'backlog/hla-attention-ui'
proposal_path = Path('/tmp/hla-attention-ui-spec/proposal.json')
expected_proposal, expected_input = sys.argv[1:]
assert hashlib.sha256(proposal_path.read_bytes()).hexdigest() == expected_proposal
raw = tomllib.loads((packet / 'release.toml').read_text())
base = 'b2d0fe393ac0971e906cce275e91f45e94422593'
assert raw['draft'] and raw['revision'] == 1 and raw['base_sha'] == base
assert raw['repo'] == 'homelab-analytics' and raw['data_class'] == 'public' and raw['size'] == 'M'
proposal = json.loads(proposal_path.read_text())
assert raw['outcome'] == proposal['outcome']
main_test = 'tests/test_attention_current_ui_acceptance.py'
assert hashlib.sha256(proposal['tests'][main_test].encode()).hexdigest() == expected_input
repo = load_repos()[raw['repo']]
lane = load_lane(raw['eligible_lanes'][0])
assert lane.max_attempts == 2 and lane.timeout_s == 2700 and lane.size_budget_lines['M'] == 700
author, reviewer = 'gpt-6.1-terra', 'opencode-go/deepseek-v4-pro'
assert raw['specification']['author_model'] == author and raw['specification']['reviewer_model'] == reviewer
spec._models(author, reviewer, lane, repo, raw['data_class'])
spec._proposal(proposal, repo, base)
assert set(raw['acceptance']['files']) == set(proposal['tests'])
for name, content in proposal['tests'].items():
    assert (packet / 'files' / name).read_text() == content
    checked = subprocess.run([str(repo.path / '.venv/bin/ruff'), 'check', '--no-cache', '--stdin-filename', name, '-'], cwd=repo.path, input=content, capture_output=True, text=True)
    assert checked.returncode == 0, checked.stdout + checked.stderr
contracts = root / 'docs/evidence/2026-11-14-product-contact/ui-stage-contracts'
freeze = json.loads((contracts / 'freeze-review.json').read_text())
for item in freeze['artifacts']:
    assert hashlib.sha256((contracts / item['path']).read_bytes()).hexdigest() == item['digest']
    assert item['digest'] in proposal['outcome'], 'outcome must bind frozen contract artifact'
commands = raw['acceptance']['exec']
assert isinstance(commands, list) and commands
before = spec.release_digest(packet)
prior_path = packet / 'specification.json'
prior_bytes = prior_path.read_bytes() if prior_path.exists() else b''
diagnostics = Path('/tmp/lanectl-hla-ui-spec-r1-review')
prompt = '''Independently adversarially review the complete HLA1593 Stage C UI acceptance in .lanectl-spec/proposal.json against canonical b2d0fe3. Existing four source-authorized record APIs are genuinely canonical after PR85, independent tests, full Make, train/dev HTTP and all CI. The current Next page still sorts ascending, labels severity1 urgent and links all rows to /review. This review concerns the FULL new UI, not API changes or a narrowed type-section-link substitute. Read the exact declared outcome and frozen public style contract artifacts; metadata pins their digests. Copying/committing those three existing-style contracts first counts in worker M700. No new taste approval or cap waiver.

Challenge actual production Next ranking before top8 with >8 unsorted mixed-domain inputs, 3>2>1, stable ties and unknown neutral/last; malformed/missing feed is error not empty. NaN cannot be HTTP JSON. Challenge real click/deep-link and strict canonical UTF8 base64url Next key decoding to the whole API key encoded exactly once, all four kind paths, distinct same-kind records, meaningful per-row facts, all multirow/nulls/precision, no fabricated anomaly currency/savings/price aggregation/recommendations/history/freshness; Current report is distinct from cashflow month. Challenge 401 redirect exception preservation, 403 no row facts or alternate report fallback, current-report404,503 unavailable including distinct Busy body,500 not sanitized as404/availability.

Independently inspect the fixture: controlled generic HTTP producer tests UI rank/error transport, not actual source authorization; separate positive canonical API must perform real source lookups and Next clicks, not merely direct API priming or exact-answer stubs. Trace how request logs distinguish actual Next reads from fixture selfchecks. Challenge hard-coded data/links, hidden facts in errors, selector-only or source-string-only acceptance, false-positive cleanup, invalid fixtures/auth/tool setup, and silent skips or vacuous JUnit. All required cases must execute, not pass by deselection/skipping. The author observed canonical named missing-rank/shared-link/detail failures with working Next, real API and cleanup; those reports are NOT your own runs/verdict. Read-only review: no source edits, generated acceptance execution, reference UI implementation, provider nesting or publication. Do not read private Vuoro source or credentials.

Write only .lanectl-spec/response.json with EXACTLY four keys: verdict string accept or revise, reason NONEMPTY STRING, trivial_pass NONEMPTY STRING describing a concrete attack and whether rejected (not boolean/null), checks NONEMPTY ARRAY of NONEMPTY STRINGS. Choose actual verdict independently. Full mandatory commands follow:
''' + json.dumps(commands, indent=2) + '\n\nFull declared task:\n' + proposal['outcome']
print('Starting actual native independent full-UI acceptance review', flush=True)
response, usage = invoke(repo, lane, base, reviewer, prompt, proposal=proposal, timeout_s=1800, run_root=diagnostics)
Path('/tmp/hla-ui-spec-r1-native-raw.json').write_text(json.dumps({'response': response, 'usage': usage}, indent=2) + '\n')
review = spec._review(response)
assert spec.release_digest(packet) == before and tomllib.loads((packet / 'release.toml').read_text())['draft']
problems = spec._base_lint(packet, repo, lane, 600) if review['verdict'] == 'accept' else ['adversarial review requests revision']
assert spec.release_digest(packet) == before
record = {'schema': spec.SCHEMA, 'release_digest': before, 'review': review, 'author_model': author, 'reviewer_model': reviewer, 'intent_digest': hashlib.sha256(proposal['outcome'].encode()).hexdigest(), 'recorded_at': datetime.now(timezone.utc).isoformat(), 'lint_problems': problems, 'usage': {'author': None, 'reviewer': usage}, 'mandatory_acceptance_commands': commands, 'prior_specification_sha256': hashlib.sha256(prior_bytes).hexdigest(), 'author_provenance': {'requested_model': author, 'kind': 'first-party acceptance author', 'task': '/root/source_r3_qualification', 'exact_runtime_variant_independently_attested': False, 'native_author_invocation_claimed': False, 'proposal_sha256': expected_proposal, 'main_input_sha256': expected_input}, 'frozen_contracts': freeze['artifacts'], 'diagnostics_root': str(diagnostics), 'invocation': 'official specification._invoke unchanged'}
tmp = packet / 'specification.next.tmp'
tmp.write_text(json.dumps(record, indent=2) + '\n'); tmp.replace(prior_path)
validation = spec.validate_for_publish(packet)
print(json.dumps({'verdict': review['verdict'], 'lint_problems': problems, 'publication_validation': validation}), flush=True)
if problems or validation:
    raise SystemExit(2)
