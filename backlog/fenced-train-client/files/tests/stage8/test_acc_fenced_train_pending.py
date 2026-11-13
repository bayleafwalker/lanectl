"""Queued starts are not terminal proof; real linked worktrees must stage."""
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize("late_receipt", [False, True])
def test_inactive_without_receipt_never_finishes_a_queued_start(monkeypatch, late_receipt):
    from lanectl import fenced_train as ft
    now = [0.0]
    polls = []
    monkeypatch.setattr(ft.time, "monotonic", lambda: now[0])
    def sleep(seconds):
        now[0] += seconds
        assert now[0] < 100, "wait exceeded the synthetic bounded deadline"
    monkeypatch.setattr(ft.time, "sleep", sleep)
    monkeypatch.setattr(ft, "WAIT_MARGIN_S", 2.0)
    def active(tool, unit):
        polls.append(now[0])
        return "active" if late_receipt and 24 <= now[0] < 25 else "inactive"
    monkeypatch.setattr(ft, "_active", active)
    monkeypatch.setattr(ft.os.path, "lexists", lambda path: late_receipt and now[0] >= 25)
    observed = ft._wait_terminal("fake-systemctl", "lanectl-train@pending.service", Path("receipt"), 60 if late_receipt else 1)
    assert observed is late_receipt
    assert now[0] >= (25 if late_receipt else 3)
    assert len(polls) > 1, "must recheck liveness while waiting for the receipt"


@pytest.mark.parametrize("detached", [False, True])
def test_stage_accepts_train_and_historical_linked_worktrees(tmp_path, detached):
    from lanectl import fenced_train as ft
    source = tmp_path / "canonical"
    source.mkdir()
    def git(*args):
        return subprocess.check_output(["git", "-C", str(source), *args], text=True).strip()
    git("init", "-q")
    (source / "sample.txt").write_text("frozen source\n")
    git("add", ".")
    git("-c", "user.name=test", "-c", "user.email=test@localhost", "commit", "-qm", "base")
    expected = git("rev-parse", "HEAD")
    checkout = tmp_path / "linked"
    args = ["worktree", "add", "-q"]
    args += ["--detach"] if detached else ["-b", "train-test"]
    git(*args, str(checkout), expected)
    assert (checkout / ".git").is_file()
    destination = tmp_path / "staged"
    commit, tracked, before = ft._stage(checkout, destination)
    assert commit == expected and tracked == ["sample.txt"]
    assert (destination / ".git").is_dir()
    assert (destination / ".git/HEAD").read_text() == expected + "\n"
    assert not (destination / ".git/objects/info/alternates").exists()
    assert (destination / "sample.txt").stat().st_nlink == 1
    assert not ft._mutation(destination, expected, tracked, before)
