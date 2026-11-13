"""Frozen sibling files are available without being collected together."""
import subprocess
import sys
from types import SimpleNamespace

import pytest

from lanectl.gates.failonbase import run_tests_at
from lanectl.lint_release import classify_failure, lint_release
from lanectl import specification


def _repo(tmp_path):
    repo = tmp_path / 'repo'
    (repo / 'tests').mkdir(parents=True)
    (repo / 'tests/__init__.py').write_text('')
    for command in (['git', 'init', '-q'], ['git', 'add', '.'],
                    ['git', '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'base']):
        subprocess.run(command, cwd=repo, check=True)
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    return repo, sha


def _files():
    return {
        'tests/test_helper.py': b'def helper(): return 42\ndef test_helper(): assert helper() == 0\n',
        'tests/test_consumer.py': b'from tests.test_helper import helper\ndef test_consumer(): assert helper() == 0\n',
    }


def _cmd():
    return f'{sys.executable} -m pytest -q -p no:cacheprovider {{files}}'


def test_selected_runs_have_all_frozen_files_but_collect_only_selected(tmp_path):
    repo, sha = _repo(tmp_path)
    files = _files()
    for name in files:
        code, output = run_tests_at(repo, sha, files, _cmd(), selected_files=[name], tail=None)
        assert code == 1 and 'assert 42 == 0' in output
        assert '1 failed' in output
    files['tests/test_helper.py'] += b'\nraise RuntimeError("unselected collection")\n'
    files['tests/test_other.py'] = b'def test_other(): assert False\n'
    code, output = run_tests_at(repo, sha, files, _cmd(), selected_files=['tests/test_other.py'], tail=None)
    assert code == 1 and '1 failed' in output and 'unselected collection' not in output
    code, output = run_tests_at(repo, sha, _files(), _cmd(), tail=None)
    assert code == 1 and '2 failed' in output


@pytest.mark.parametrize('selected', [[], ['tests/missing.py'], ['tests/test_helper.py', 'tests/missing.py']])
def test_invalid_selection_is_rejected(tmp_path, selected):
    repo, sha = _repo(tmp_path)
    with pytest.raises(ValueError):
        run_tests_at(repo, sha, _files(), _cmd(), selected_files=selected)


def test_missing_test_support_is_spec_gap_even_with_expected_failure():
    missing = "E   ModuleNotFoundError: No module named 'tests.test_typo'"
    assert classify_failure(missing) == 'spec-gap'
    assert classify_failure('E   AssertionError: missing feature\n' + missing) == 'spec-gap'
    assert classify_failure('_____ test_feature _____\nE   AssertionError: missing\n'
                            '_____ ERROR collecting tests/test_typo.py _____\n' + missing) == 'spec-gap'
    assert classify_failure("E   ModuleNotFoundError: No module named 'lanectl.capacity'") == 'expected'
    missing_symbol = "E   ImportError: cannot import name 'missing_helper' from 'tests.test_helper' (/tmp/tests/test_helper.py)"
    assert classify_failure(missing_symbol) == 'spec-gap'
    assert classify_failure('_____ test_feature _____\nE   AssertionError: missing\n'
                            '_____ ERROR collecting tests/test_other.py _____\n' + missing_symbol) == 'spec-gap'
    assert classify_failure("E   ImportError: cannot import name 'new' from 'lanectl.product'") == 'expected'
    assert classify_failure("E   Failed: DID NOT RAISE <class 'ImportError'>") == 'expected'


def test_specification_materializes_every_file_and_selects_one(tmp_path, monkeypatch):
    files = _files()
    for name, data in files.items():
        dest = tmp_path / 'files' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    monkeypatch.setattr(specification, 'load_release', lambda path: SimpleNamespace(acceptance=SimpleNamespace(files=tuple(files)), base_sha='base'))
    calls = []
    def run(repo, rev, context, cmd, setup, **kwargs):
        calls.append((context, kwargs['selected_files']))
        return 1, 'E   AssertionError: missing feature'
    monkeypatch.setattr(specification, 'run_tests_at', run)
    repo = SimpleNamespace(path=tmp_path, test_cmd='pytest {files}', setup_cmd='')
    assert specification._base_lint(tmp_path, repo, None, 30) == []
    assert calls == [(files, [name]) for name in files]


def test_release_lint_uses_full_context_per_file(tmp_path, monkeypatch):
    repo, sha = _repo(tmp_path)
    home = tmp_path / 'home'
    (home / 'governance/lanes').mkdir(parents=True)
    (home / 'governance/repos.toml').write_text(f'[repos.r]\npath = "{repo}"\ntest_cmd = "{_cmd()}"\ncheck_cmd = "true"\nworktree_root = "{tmp_path}/wt"\n')
    monkeypatch.setenv('LANECTL_HOME', str(home))
    release = home / 'backlog/item'
    for name, data in _files().items():
        dest = release / 'files' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    (release / 'release.toml').write_text(f'''id = "item"
repo = "r"
base_sha = "{sha}"
title = "t"
outcome = "o"
task_class = "glue"
size = "S"
data_class = "public"
[scope]
paths = ["tests/**"]
[acceptance]
exec = ["true"]
files = ["tests/test_helper.py", "tests/test_consumer.py"]
''')
    assert lint_release(release) == []
    # A support file that is not itself a test is still part of the frozen context.
    helper = release / 'files/tests/support.py'
    helper.write_bytes(b'def value(): return 42\n')
    consumer = release / 'files/tests/test_consumer.py'
    consumer.write_bytes(b'from tests.support import value\ndef test_consumer(): assert value() == 0\n')
    manifest = release / 'release.toml'
    manifest.write_text(manifest.read_text().replace('"tests/test_consumer.py"]', '"tests/test_consumer.py", "tests/support.py"]'))
    assert lint_release(release) == []
