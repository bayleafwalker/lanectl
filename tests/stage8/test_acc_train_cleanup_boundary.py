"""Safe interceptors prove cleanup never targets canonical data."""
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("target", ["canonical", "ancestor", "alias"])
def test_cleanup_refuses_paths_that_contain_the_canonical_checkout(tmp_path, monkeypatch, target):
    from lanectl import runner
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    marker = canonical / "must-survive"
    marker.write_text("synthetic canonical data")
    alias = tmp_path / "alias"
    alias.symlink_to(canonical, target_is_directory=True)
    path = {"canonical": canonical, "ancestor": tmp_path, "alias": alias}[target]
    removed, git_calls = [], []
    monkeypatch.setattr(runner, "git", lambda repo, *args, **kwargs: git_calls.append(args) or "")
    # Intercept before deletion. The defective base is safe to execute here.
    monkeypatch.setattr(runner.shutil, "rmtree", lambda path, **kwargs: removed.append(Path(path)))
    try:
        runner._discard(SimpleNamespace(path=canonical), path)
    except (RuntimeError, ValueError):
        pass
    assert removed == [], "cleanup attempted deletion containing canonical data"
    assert not any(args[:2] == ("worktree", "remove") for args in git_calls)
    assert marker.read_text() == "synthetic canonical data"


def test_cleanup_still_removes_an_independent_attempt_checkout(tmp_path, monkeypatch):
    from lanectl import runner
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    checkout = tmp_path / "attempt"
    checkout.mkdir()
    marker = canonical / "must-survive"
    marker.write_text("synthetic")
    git_calls = []
    monkeypatch.setattr(runner, "git", lambda repo, *args, **kwargs: git_calls.append(args) or "")
    runner._discard(SimpleNamespace(path=canonical), checkout)
    assert not checkout.exists()
    assert marker.read_text() == "synthetic"
    assert ("worktree", "remove", "--force", str(checkout)) in git_calls
