"""Base failure must reach product assertions, not fail a fixture assertion."""
from pathlib import Path
import json
import subprocess
import sys

import pytest

from lanectl import cli, specification
from lanectl.config import load_release
from lanectl.lint_release import classify_failure
from tests.stage8.test_specification import fake_adapter, make


SETUP = '''import pytest
@pytest.fixture
def unavailable():
    assert False, "locked frontend modules unavailable"
def test_fixture(unavailable):
    assert True
'''
CALL = 'def test_product():\n    assert 1 == 2, "product behavior absent"\n'


def run_pytest(tmp_path, source):
    (tmp_path / 'test_subject.py').write_text(source)
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', '-q', '--tb=short', '-p', 'no:cacheprovider'],
        cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1, result.stdout + result.stderr
    return result.stdout + result.stderr


@pytest.mark.parametrize('source,expected', [
    (SETUP, 'spec-gap'), (CALL, 'expected'), (SETUP + CALL, 'spec-gap')],
    ids=['setup-assertion', 'call-assertion', 'mixed-phases'])
def test_real_pytest_setup_call_and_mixed_phases(tmp_path, source, expected):
    output = run_pytest(tmp_path, source)
    if source != CALL:
        assert 'ERROR at setup of test_fixture' in output
    assert classify_failure(output) == expected, output


def test_real_setup_missing_product_import_retains_expected_contract(tmp_path):
    source = SETUP.replace('assert False, "locked frontend modules unavailable"',
                           'import product_feature_not_implemented_21903')
    output = run_pytest(tmp_path, source)
    assert 'ModuleNotFoundError' in output
    assert classify_failure(output) == 'expected'


def test_setup_import_is_not_reclassified_by_assertion_word_in_source(tmp_path):
    source = SETUP.replace('assert False, "locked frontend modules unavailable"',
                           'raise ImportError("feature absent; AssertionError is only text")')
    output = run_pytest(tmp_path, source)
    assert classify_failure(output) == 'expected'


def test_recorded_fresh_clone_setup_errors_are_not_a_semantic_base_failure():
    root = Path(__file__).resolve().parents[2]
    output = (root / 'docs/evidence/2026-11-14-product-contact/'
              'onboarding-native-review-and-fresh-base/official-base-lint.log').read_text()
    assert '16 errors' in output and 'Node20/locked modules unavailable' in output
    assert classify_failure(output) == 'spec-gap'


def test_real_base_lint_records_fixture_problem_and_refuses_publication(estate):
    def adapter(**kwargs):
        result = fake_adapter(**kwargs)
        if 'adversarial reviewer' not in kwargs['prompt']:
            response = {'outcome': 'Add product behavior',
                        'tests': {'tests/test_acc_spec.py': SETUP}}
            (kwargs['worktree'] / '.lanectl-spec/response.json').write_text(json.dumps(response))
        return result

    release = make(estate, adapter_fn_override=adapter)
    evidence = json.loads((release / 'specification.json').read_text())
    assert evidence['lint_problems'] == ['spec-gap: tests/test_acc_spec.py']
    assert specification.validate_for_publish(release)
    assert cli.main(['backlog', 'publish', 'spec-sub']) == 1
    assert load_release(release).draft
    assert not any(e['type'] == 'release.published' for e in estate[2].read())
