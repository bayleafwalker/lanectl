"""Frozen acceptance for #2889's opt-in separate-UID command boundary."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess

import pytest


def test_new_mode_delegates_without_namespace_or_host_shell(estate, monkeypatch):
    from lanectl import config, fenced_train, runner, sandbox
    path = Path(os.environ["LANECTL_HOME"]) / "governance/repos.toml"
    path.write_text(path.read_text() + '\ntrain_isolation = "systemd"\n')
    policy = config.load_repos()["target"]
    repo, _, _ = estate
    seen = []
    def command(got_repo, checkout, cmd, timeout_s=1800):
        seen.append((got_repo, checkout, cmd))
        return subprocess.CompletedProcess(cmd, 0, "fenced", "")
    monkeypatch.setattr(fenced_train, "run_command", command)
    monkeypatch.setattr(sandbox, "for_train", lambda **kw: pytest.fail("namespace fallback"))
    result = runner._train_command(policy, repo, "synthetic check")
    assert result.returncode == 0 and result.stdout == "fenced"
    assert seen == [(policy, repo, "synthetic check")]


def test_receipts_bind_identity_request_and_actual_service_exit():
    from lanectl.fenced_train import receipt_returncode
    good = {"version": 1, "train_id": "proof-1", "request_sha256": "sha256:" + "a" * 64,
            "outcome": "succeeded", "service_result": "success", "exit_code": "exited", "exit_status": "0"}
    def code(record):
        return receipt_returncode(record, train_id="proof-1", request_sha256=good["request_sha256"])
    assert code(good) == 0
    for key, wrong in (("version", 2), ("train_id", "foreign"), ("request_sha256", "sha256:" + "b" * 64)):
        with pytest.raises(ValueError):
            code(dict(good, **{key: wrong}))
    for key in good:
        missing = dict(good)
        del missing[key]
        with pytest.raises(ValueError):
            code(missing)
    for outcome, service, status in (("failed", "exit-code", "7"), ("timeout", "timeout", "124"),
                                      ("cancelled", "signal", "15"), ("rejected", "exit-code", "1")):
        assert code(dict(good, outcome=outcome, service_result=service, exit_status=status)) != 0
    # An attacker changing just outcome cannot promote the systemd exit.
    incoherent = dict(good, service_result="exit-code", exit_status="7")
    try:
        value = code(incoherent)
    except ValueError:
        pass
    else:
        assert value != 0


def test_unavailable_service_cannot_execute_candidate_on_host(estate, monkeypatch, tmp_path):
    from lanectl import fenced_train, runner
    repo, _, _ = estate
    policy = replace(runner.load_repos()["target"], train_isolation="systemd")
    # No systemctl on trusted PATH is a real launcher-availability failure.
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    marker = tmp_path / "must-not-run"
    result = runner._train_command(policy, repo, "touch " + str(marker))
    assert result.returncode != 0
    assert not marker.exists()
    assert result.stderr and ("fenc" in result.stderr.lower() or "systemd" in result.stderr.lower())
