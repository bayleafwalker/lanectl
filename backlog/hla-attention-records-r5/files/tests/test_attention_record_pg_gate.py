"""Fail closed unless the three frozen API PostgreSQL cases actually pass."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

TEST_FILE = 'tests/test_attention_record_api.py'
CASES = (
    'test_published_postgres_attention_records',
    'test_published_postgres_missing_identity_column_is_unavailable',
    'test_published_postgres_empty_identity_never_resolves_forged_key',
)


def validate_report(path: Path) -> None:
    """Require precisely the named three successful cases, with no skips/errors."""
    root = ET.parse(path).getroot()
    if root.tag not in ('testsuites', 'testsuite'):
        raise ValueError('unexpected JUnit root')
    suites = list(root.iter('testsuite'))
    if not suites:
        raise ValueError('missing JUnit suite')
    cases = list(root.iter('testcase'))
    expected = set(CASES)
    names = [case.get('name') for case in cases]
    if len(cases) != len(CASES) or set(names) != expected or len(set(names)) != len(CASES):
        raise ValueError(f'expected exactly three named cases, got {names!r}')
    if any(case.get('classname') != 'tests.test_attention_record_api' for case in cases):
        raise ValueError('unexpected test module')
    if any(case.find(tag) is not None for case in cases for tag in ('skipped', 'failure', 'error')):
        raise ValueError('a case was skipped or failed')
    # Reject malformed or inconsistent summaries, including errors outside testcases.
    if len(suites) != 1:
        raise ValueError('expected exactly one suite')
    suite = suites[0]
    for key, value in (('tests', 3), ('skipped', 0), ('failures', 0), ('errors', 0)):
        if int(suite.attrib[key]) != value:
            raise ValueError(f'invalid JUnit {key} count')
    if list(root.iter('failure')) or list(root.iter('error')) or list(root.iter('skipped')):
        raise ValueError('JUnit contains a failure, error or skip')


def main() -> int:
    with tempfile.TemporaryDirectory(prefix='attention-pg-gate-') as temp:
        report = Path(temp) / 'pytest.xml'
        command = [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
                   '-m', 'integration and slow', *(f'{TEST_FILE}::{case}' for case in CASES),
                   '--junitxml', str(report)]
        result = subprocess.run(command, check=False)
        if result.returncode:
            print(f'PostgreSQL gate: pytest failed with exit {result.returncode}', file=sys.stderr)
            return result.returncode if 0 < result.returncode < 256 else 1
        try:
            validate_report(report)
        except (OSError, ET.ParseError, ValueError, KeyError) as exc:
            print(f'PostgreSQL gate: invalid or incomplete report: {exc}', file=sys.stderr)
            return 1
        print('PostgreSQL gate: all three named cases passed without skips')
        return 0


if __name__ != '__main__':
    import pytest

    @pytest.mark.integration
    def test_attention_record_postgres_gate() -> None:
        assert main() == 0


if __name__ == '__main__':
    raise SystemExit(main())
