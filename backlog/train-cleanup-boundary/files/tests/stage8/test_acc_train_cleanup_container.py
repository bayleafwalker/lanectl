"""The shared managed container is never an individual disposable checkout."""
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("layout", ["inside", "outside"])
@pytest.mark.parametrize("alias", [False, True])
@pytest.mark.parametrize("operation", ["discard", "historical"])
def test_shared_container_and_alias_are_protected(tmp_path, monkeypatch, layout, alias, operation):
    from lanectl import runner
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    managed = canonical / ".worktrees" if layout == "inside" else tmp_path / "managed"
    managed.mkdir()
    sibling = managed / "other-attempt"
    sibling.mkdir()
    (sibling / "must-survive").write_text("synthetic")
    target = tmp_path / "container-alias" if alias else managed
    if alias:
        target.symlink_to(managed, target_is_directory=True)
    repo = SimpleNamespace(path=canonical, worktree_root=managed)
    monkeypatch.setattr(runner, "git", lambda *args, **kwargs: "")
    if operation == "discard":
        removed = []
        with monkeypatch.context() as guard:
            guard.setattr(runner.shutil, "rmtree", lambda path, **kwargs: removed.append(Path(path)))
            try:
                runner._discard(repo, target)
            except (RuntimeError, ValueError):
                pass
        assert not removed, "cleanup attempted deletion of every managed checkout"
    else:
        with runner._historical_checkout(repo, target, "a" * 40) as checkout:
            assert checkout.resolve() != managed.resolve()
            assert not managed.resolve().is_relative_to(checkout.resolve())
    assert (sibling / "must-survive").read_text() == "synthetic"
