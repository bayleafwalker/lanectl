"""Protect canonical contents and preserve successful historical recovery."""
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest


@pytest.mark.parametrize("kind", ["source", "git", "source-alias"])
def test_cleanup_never_deletes_unmanaged_canonical_contents(tmp_path, monkeypatch, kind):
    from lanectl import runner
    canonical = tmp_path / "canonical"
    source = canonical / "src"
    source.mkdir(parents=True)
    gitdir = canonical / ".git"
    gitdir.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(source, target_is_directory=True)
    target = {"source": source, "git": gitdir, "source-alias": alias}[kind]
    removed, calls = [], []
    monkeypatch.setattr(runner, "git", lambda repo, *args, **kwargs: calls.append(args) or "")
    monkeypatch.setattr(runner.shutil, "rmtree", lambda path, **kwargs: removed.append(Path(path)))
    repo = SimpleNamespace(path=canonical, worktree_root=tmp_path / "managed")
    try:
        runner._discard(repo, target)
    except (RuntimeError, ValueError):
        pass
    assert not removed
    assert not any(args[:2] == ("worktree", "remove") for args in calls)


def test_explicit_managed_checkout_inside_canonical_can_still_be_cleaned(tmp_path, monkeypatch):
    from lanectl import runner
    canonical = tmp_path / "canonical"
    managed = canonical / ".worktrees"
    target = managed / "attempt"
    target.mkdir(parents=True)
    marker = canonical / "must-survive"
    marker.write_text("synthetic")
    monkeypatch.setattr(runner, "git", lambda *args, **kwargs: "")
    runner._discard(SimpleNamespace(path=canonical, worktree_root=managed), target)
    assert not target.exists() and marker.read_text() == "synthetic"


@pytest.mark.parametrize("kind", ["ancestor", "source"])
def test_historical_checks_reconstruct_instead_of_granting_canonical_overlap(tmp_path, monkeypatch, kind):
    from lanectl import runner
    canonical = tmp_path / "canonical"
    source = canonical / "src"
    source.mkdir(parents=True)
    recorded = tmp_path if kind == "ancestor" else source
    repo = SimpleNamespace(path=canonical, worktree_root=tmp_path / "managed")
    def git(repo, *args, **kwargs):
        if args[:2] == ("worktree", "add"):
            Path(args[-2]).mkdir(parents=True)
        return ""
    monkeypatch.setattr(runner, "git", git)
    cleaned = []
    monkeypatch.setattr(runner, "_discard", lambda repo, path: cleaned.append(path))
    with runner._historical_checkout(repo, recorded, "a" * 40) as checkout:
        assert checkout != recorded
        assert not canonical.resolve().is_relative_to(checkout.resolve())
        assert not checkout.resolve().is_relative_to(canonical.resolve())
    assert len(cleaned) == 1 and cleaned[0] != recorded


def test_completed_historical_land_survives_refused_canonical_cleanup(estate, monkeypatch):
    from lanectl import runner
    from tests.stage8.test_work_sync_extra import _train, _head
    canonical, release, log = estate
    release("cleanup-history", "def test_ok():\n    assert True\n")
    base = _head(canonical)
    _train(log, canonical, "cleanup-history", base)
    built = [e["data"] for e in log.read() if e["type"] == "train.built"][-1]
    log.append("train.built", dict(built, worktree=str(canonical)))
    monkeypatch.setattr(runner, "_train_command", lambda *args: subprocess.CompletedProcess([], 0, "synthetic checked", ""))
    attempt = runner.load_repos()["target"].worktree_root / "cleanup-history-a1"
    attempt.mkdir(parents=True)
    result = runner.land(log, "tt")
    assert result.startswith("landed"), result
    assert canonical.is_dir() and _head(canonical) == base
    assert any(e["type"] == "item.landed" for e in log.read())
    assert not attempt.exists(), "refused canonical cleanup must not abandon safe attempt cleanup"
