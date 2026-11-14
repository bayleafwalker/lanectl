"""Review the unchanged full API acceptance against the landed source layer."""
import hashlib
import json
import subprocess
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from lanectl import specification as spec
from lanectl.config import load_lane, load_repos
from lanectl_persistent_spec_review import invoke

root = Path("/projects/dev/lanectl")
packet = root / "backlog/hla-attention-records-r5"
proposal_path = Path("/tmp/hla-attention-api-r4-proposal.json")
expected_proposal = "b540dc5491e4d23d69d1a79b67d716aab7675e5b620df263c47072a3c250c452"
expected_fixture = "34da78c8cb79c5ecc6d38e740c6b2ee90433dc000e6633cb3bf853aff6bb3abb"
expected_base = "30c0caf6c78d257ff5db79f42cca0b56a0f934b9"
diagnostics = Path("/tmp/lanectl-hla-api-r4-review")
assert hashlib.sha256(proposal_path.read_bytes()).hexdigest() == expected_proposal
raw = tomllib.loads((packet / "release.toml").read_text())
assert raw["revision"] == 4 and raw["draft"] and raw["base_sha"] == expected_base
fixture = packet / "files/tests/test_attention_record_api.py"
assert hashlib.sha256(fixture.read_bytes()).hexdigest() == expected_fixture
assert len(fixture.read_text().splitlines()) == 1173
assert raw["scope"]["paths"] == [
    "apps/api/app.py", "apps/api/routes/attention_record_routes.py",
    "apps/web/frontend/generated/**", "tests/**", "docs/**",
]
proposal = json.loads(proposal_path.read_text())
repo = load_repos()[raw["repo"]]
lane = load_lane(raw["eligible_lanes"][0])
author, reviewer = "gpt-6.1-terra", "opencode-go/deepseek-v4-pro"
spec._models(author, reviewer, lane, repo, raw["data_class"])
spec._proposal(proposal, repo, expected_base)
assert raw["outcome"] == proposal["outcome"]
for name, text in proposal["tests"].items():
    assert (packet / "files" / name).read_text() == text
    checked = subprocess.run(
        [str(repo.path / ".venv/bin/ruff"), "check", "--no-cache",
         "--stdin-filename", name, "-"],
        cwd=repo.path, input=text, capture_output=True, text=True,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
commands = raw["acceptance"]["exec"]
assert len(commands) == 2 and "integration and slow" in commands[1]
prior = json.loads((packet / "specification.json").read_text())
prior_sha = hashlib.sha256((packet / "specification.json").read_bytes()).hexdigest()
digest = spec.release_digest(packet)
prompt = """Perform an independent adversarial acceptance review of the complete four-kind HTTP adapter revision4. Read .lanectl-spec/proposal.json and canonical source30c0caf. The source prerequisite has genuinely landed through PR83 after native done0, independent source/PG/parity/full verification, checked train/dev and all canonical CI. Canonical provides the public ReportingService.get_attention_record and AttentionRecordNotFoundError/UnavailableError in overview. This revision is the ORIGINAL full four-HTTP layer, with unchanged1173-line frozen acceptance, on that actual source. No source-reader, reporting-service or legacy report_routes edits are permitted; new routes belong in attention_record_routes.py with minimal app.py registration, generated contracts and worker regression tests, all within unchanged M700.

Independently challenge the complete own-source authorization, four routes/row models, whole opaque IDs and encoded slash routing/OpenAPI shape, exact current-publication groups, no fallback, NULL/empty identity admission versus unsupported mutations, provable404 versus safe detail-only503 with no fields/driver markers, and preservation of canonical Busy retry response and unrelated programming errors. Trace against canonical source, not unaccepted implementation code or reported results. Check tests cannot pass by hard-coded examples, whole-source fetching/filtering, scalar-only or false-WHERE queries. Check whether declared preflight/explicit real-PG selection plus integration-owner no-skip qualification enforce the required behavior; flag missing mechanical enforcement rather than treating outcome prose as a test. Confirm canonical fails on the genuinely missing HTTP feature rather than imports, fixtures, unavailable tools or setup.

Planning observations are NOT your runs or your verdict: exact frozen tests passed29fast+3actualPG over a scratch HTTP-only reference overlay without overwriting the landed source. Source-only control failed missing record route; an unfiltered-query injection failed the bound-selection observer. API-layer reference measured589 additions including460 generated and72 worker regressions, not a cap exemption. One old worker Busy regression patches removed attention_records.run_on_warehouse and fails before HTTP; a separate real lower acquisition probe gives canonical503 Retry-After5 and200 before/after. New implementation must use the actual current boundary; frozen test bytes remain unchanged. Never use the unaccepted reference as oracle or approve it. All four HTTP kinds, full later meaningful ranked UI, actual verification/train/dev/canonical CI remain required; this API layer is not whole HLA1593.

Read-only review: no source edits, no generated acceptance execution and no implementation. Write only .lanectl-spec/response.json with EXACTLY four keys: verdict is the string accept or revise; reason is a NONEMPTY STRING; trivial_pass is a NONEMPTY STRING describing a trivial-pass attack and whether the contract rejects it (never boolean or null); checks is a NONEMPTY ARRAY of NONEMPTY STRINGS. Choose the actual verdict independently. Never publish. Full declared task follows:
""" + proposal["outcome"]
print("Starting actual native GoPro R4 review of unchanged1173/API-only scope", flush=True)
review_raw, usage = invoke(
    repo, lane, expected_base, reviewer, prompt, proposal=proposal,
    timeout_s=1800, run_root=diagnostics,
)
Path("/tmp/hla-api-r4-native-raw.json").write_text(
    json.dumps({"response": review_raw, "usage": usage}, indent=2) + "\n"
)
review = spec._review(review_raw)
assert spec.release_digest(packet) == digest
assert tomllib.loads((packet / "release.toml").read_text())["draft"]
print(json.dumps(review), flush=True)
problems = (
    spec._base_lint(packet, repo, lane, 600)
    if review["verdict"] == "accept"
    else ["adversarial review requests revision"]
)
assert spec.release_digest(packet) == digest
evidence = dict(
    schema=spec.SCHEMA, release_digest=digest, review=review,
    author_model=author, reviewer_model=reviewer,
    intent_digest=hashlib.sha256(proposal["outcome"].encode()).hexdigest(),
    recorded_at=datetime.now(timezone.utc).isoformat(),
    lint_problems=problems,
    usage={"author": (prior.get("usage") or {}).get("author"), "reviewer": usage},
    mandatory_acceptance_commands=commands,
    prior_specification_sha256=prior_sha,
    scope_revision={
        "model_requested": "gpt-6.1-terra",
        "harness": "first-party API planner agent",
        "task": "/root/source_r3_qualification",
        "proposal_sha256": expected_proposal,
        "frozen_input_unchanged": True,
        "frozen_input_sha256": expected_fixture,
        "new_author_invocation_for_frozen_tests": False,
        "canonical_source": expected_base,
        "original_full_api_scope_preserved": True,
        "unaccepted_reference_is_not_implementation_approval": True,
    },
    diagnostics_root=str(diagnostics),
    invocation="official specification._invoke unchanged",
)
temporary = packet / "specification.next.tmp"
temporary.write_text(json.dumps(evidence, indent=2) + "\n")
temporary.replace(packet / "specification.json")
validation = spec.validate_for_publish(packet)
print(json.dumps({"verdict": review["verdict"], "lint_problems": problems,
                  "publication_validation": validation}), flush=True)
if problems or validation:
    raise SystemExit(2)
