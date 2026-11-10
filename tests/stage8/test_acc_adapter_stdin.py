"""Acceptance: s3-adapter-stdin - worker subprocesses never inherit the runner's stdin."""
import subprocess

import pytest

from lanectl import adapters, adapters_opencode


class _Stop(Exception):
    pass


def _capture(seen):
    def fake(*args, **kwargs):
        seen.update(kwargs)
        raise _Stop()
    return fake


def test_opencode_worker_stdin_is_devnull(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(adapters_opencode.subprocess, "Popen", _capture(seen))
    with pytest.raises(_Stop):
        adapters_opencode.run_opencode(model="opencode-go/deepseek-v4.1-flash", worktree=tmp_path,
                                       prompt="p", status_file=tmp_path / "s.json", timeout_s=5,
                                       external=True)
    assert seen.get("stdin") is subprocess.DEVNULL


def test_agentops_dispatch_stdin_is_devnull(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(adapters.shutil, "which", lambda name: "/bin/agentops")
    monkeypatch.setattr(adapters.subprocess, "run", _capture(seen))
    with pytest.raises(_Stop):
        adapters.agentops_dispatch("codex", "gpt-x", tmp_path, "p", tmp_path / "s.json", 5, False)
    assert seen.get("stdin") is subprocess.DEVNULL
