"""Loaded credentials are read on demand without exporting them to checks."""
import os
from pathlib import Path
import subprocess

import pytest

from lanectl.coordination import CoordinationError, configured


def client(tmp_path, monkeypatch, source='credential_name="lanectl-runner"'):
    (tmp_path / 'governance').mkdir(exist_ok=True)
    (tmp_path / 'governance/vuoro.toml').write_text(
        '[repos.example]\nendpoint="https://example.invalid"\nrepo_id="example"\n'
        'expected_environment="test"\n' + source + '\n')
    monkeypatch.setenv('CREDENTIALS_DIRECTORY', str(tmp_path / 'credentials'))
    return configured('example', root=tmp_path, journal_path=tmp_path / 'journal.sqlite').client


def test_credential_is_lazy_rotatable_and_absent_from_check_environment(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    directory = tmp_path / 'credentials'
    directory.mkdir()
    credential = directory / 'lanectl-runner'
    for token in ('synthetic-first', 'synthetic-rotated'):
        credential.write_text(token + '\n')
        assert c.token_resolver() == token
        assert token not in os.environ.values()
        check = subprocess.run(['/bin/sh', '-c', 'env'], capture_output=True, check=True)
        assert token.encode() not in check.stdout
        assert b'LANECTL_RUNNER_TOKEN=' not in check.stdout


@pytest.mark.parametrize('value', [None, '', ' ', '\n', 'two words', 'two\nlines'])
def test_missing_or_malformed_credential_refuses(tmp_path, monkeypatch, value):
    c = client(tmp_path, monkeypatch)
    directory = tmp_path / 'credentials'
    directory.mkdir()
    if value is not None:
        (directory / 'lanectl-runner').write_text(value)
    with pytest.raises(CoordinationError, match='credential'):
        c.token_resolver()
    monkeypatch.delenv('CREDENTIALS_DIRECTORY')
    with pytest.raises(CoordinationError, match='unavailable'):
        c.token_resolver()


@pytest.mark.parametrize('source', ['credential_name="../secret"', 'credential_name="/secret"',
                                  'credential_name=".."', 'credential_name=""',
                                  'credential_name="runner"\ntoken_env="TOKEN"'])
def test_credential_source_is_unambiguous_and_confined(tmp_path, monkeypatch, source):
    with pytest.raises(CoordinationError):
        client(tmp_path, monkeypatch, source)
