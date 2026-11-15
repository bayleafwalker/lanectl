from pathlib import Path
import argparse
import ast
import hashlib
import json
import os
import xml.etree.ElementTree as ET

from lanectl import specification as spec
from lanectl.config import load_lane, load_repos

parser = argparse.ArgumentParser()
parser.add_argument('--reference-junit', required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parent
binding = json.loads((root / 'source-binding.json').read_text())
draft = root / 'qualified-draft'
assert spec.release_digest(draft) == binding['release_digest']
test = draft / 'files/tests/test_hla1587_acceptance.py'
assert hashlib.sha256(test.read_bytes()).hexdigest() == binding['test_sha256']
tree = ast.parse(test.read_text())
declaration = next(node for node in tree.body if isinstance(node, ast.Assign)
    and any(isinstance(target, ast.Name) and target.id == 'EXPECTED_CASES'
            for target in node.targets))
expected = ast.literal_eval(declaration.value)
assert len(expected) == len(set(expected))

def population(path):
    cases = list(ET.parse(path).getroot().iter('testcase'))
    names = [case.attrib['name'] for case in cases]
    assert len(names) == len(set(names)) and set(names) == set(expected)
    assert not any(case.find('error') is not None or case.find('skipped') is not None
                   for case in cases), 'Infrastructure error or skip in actual population'
    return {case.attrib['name']: 'failed' if case.find('failure') is not None else 'passed'
            for case in cases}

reference = population(Path(args.reference_junit))
assert 'failed' in reference.values() and 'passed' in reference.values()
junit = root / 'official-base-junit.xml'
assert not junit.exists(), 'Do not overwrite a prior qualification run'
os.environ['PYTEST_ADDOPTS'] = '--junitxml=' + str(junit) + ' --basetemp=' + str(root / 'pytest-official-base')
os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(root / 'absent-native-browser-cache')
assert not Path(os.environ['PLAYWRIGHT_BROWSERS_PATH']).exists()
os.environ.pop('LD_LIBRARY_PATH', None)
os.environ.pop('HLA_FORCE_BROWSER_FALLBACK', None)
actual_run = spec.run_tests_at
observed = {}

def recorded(*args, **kwargs):
    code, output = actual_run(*args, **kwargs)
    (root / 'official-base-lint.log').write_text(output)
    observed.update(code=code)
    return code, output

spec.run_tests_at = recorded
try:
    problems = spec._base_lint(draft, load_repos()['homelab-analytics'],
        load_lane('implement'), 900)
finally:
    spec.run_tests_at = actual_run
actual = population(junit)
assert actual == reference, 'Official base case statuses differ from the qualified frozen source'
assert observed['code'] == 1 and problems == [], (observed, problems)
assert spec.release_digest(draft) == binding['release_digest']
proof = dict(binding=binding, problems=problems, returncode=observed['code'],
    exact_population_qualified=True, passed=sum(v == 'passed' for v in actual.values()),
    failed=sum(v == 'failed' for v in actual.values()), errors=0, skipped=0,
    cases=actual, ordinary_repo_test_command=True,
    native_browser_cache_absent=True, inherited_ld_library_path_removed=True,
    forced_browser_selection=False, publication=False, candidate='UNOBSERVED')
(root / 'official-base-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
print(json.dumps(proof), flush=True)
