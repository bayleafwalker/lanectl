import json
import os
import subprocess
import sys
from pathlib import Path

from lanectl import adapters, specification
from lanectl.config import load_lane, load_repos
from lanectl.adapters import AdapterResult


def test_specification_local_model_uses_original_named_sandbox(estate, monkeypatch):
    repo, _, _ = estate
    seen = []

    def local(*, sandbox, stop_callback, worktree, **kwargs):
        assert sandbox.mode == 'systemd-run' and sandbox.unit
        assert stop_callback.__self__ == sandbox
        seen.append(sandbox)
        (Path(worktree) / '.lanectl-spec/response.json').write_text(json.dumps({'response': 'synthetic'}))
        return AdapterResult('done', 0, '', None)

    monkeypatch.setitem(adapters.ADAPTERS, 'local', local)
    spec = load_repos()['target']
    base = specification._git(repo, 'rev-parse', 'HEAD')
    result, _ = specification._invoke(spec, load_lane('implement'), base, 'local/worker-fast', 'synthetic')
    assert result == {'response': 'synthetic'} and len(seen) == 1


def test_spec_model_cannot_overwrite_control_log_or_recovery_journal(estate, tmp_path, monkeypatch):
    repo, _, log = estate
    journal = log.path.parent / 'owner-recovery.sqlite'
    journal.write_text('coordinator-only')
    original = log.path.read_bytes()
    binary = tmp_path / 'bin'
    binary.mkdir()
    worker = binary / 'claude'
    worker.write_text(f'#!{sys.executable}\nimport json\nfrom pathlib import Path\n'
        f'targets = {list(map(str, [log.path, journal]))!r}\nblocked = []\n'
        'for target in targets:\n'
        '    try:\n        Path(target).write_text("corrupted")\n        blocked.append(False)\n'
        '    except OSError:\n        blocked.append(True)\n'
        'Path(".lanectl-spec/response.json").write_text(json.dumps({"blocked":blocked}))\n')
    worker.chmod(0o755)
    monkeypatch.setenv('PATH', str(binary) + os.pathsep + os.environ['PATH'])

    def adapter(**kwargs):
        result = subprocess.run(['claude'], cwd=kwargs['worktree'], env=kwargs['env'],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return AdapterResult('done', 0, '', None)

    result, _ = specification._invoke(load_repos()['target'], load_lane('implement'),
        specification._git(repo, 'rev-parse', 'HEAD'), 'claude-sonnet-5-5', 'synthetic', adapter_fn=adapter)
    assert result['blocked'] == [True, True]
    assert log.path.read_bytes() == original and journal.read_text() == 'coordinator-only'
