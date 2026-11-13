"""No candidate parent symlink may induce a coordinator file read."""
import os
from pathlib import Path
import stat

import pytest


@pytest.mark.parametrize("whole_repo", [False, True])
def test_inspection_never_opens_files_through_candidate_parent_links(tmp_path, monkeypatch, whole_repo):
    from lanectl import fenced_train as ft
    root = tmp_path / "repo"
    (root / "nested").mkdir(parents=True)
    (root / "nested/file").write_text("tracked")
    (root / ".git").mkdir()
    (root / ".git/HEAD").write_text("a" * 40 + "\n")
    before = ft._manifest(root, ["nested/file"])
    outside = tmp_path / "outside"
    (outside / ".git").mkdir(parents=True)
    (outside / ".git/HEAD").write_text("a" * 40 + "\n")
    (outside / "file").write_text("synthetic-only")
    if whole_repo:
        root.rename(tmp_path / "saved")
        root.symlink_to(outside, target_is_directory=True)
    else:
        (root / "nested/file").unlink()
        (root / "nested").rmdir()
        (root / "nested").symlink_to(outside, target_is_directory=True)
    real_open = os.open
    attempted = []
    def guarded(path, flags, *args, **kwargs):
        # Opening a directory with NOFOLLOW is the safe parent-walk operation;
        # the kernel refuses symlinks before any outside content is accessed.
        if not (flags & os.O_DIRECTORY and flags & os.O_NOFOLLOW):
            candidate = Path(path)
            if not candidate.is_absolute() and kwargs.get("dir_fd") is not None:
                candidate = Path(os.readlink(f"/proc/self/fd/{kwargs['dir_fd']}")) / candidate
            if candidate.resolve().is_relative_to(outside):
                attempted.append(str(candidate))
                raise PermissionError("synthetic interceptor prevented an outside read")
        return real_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(ft.os, "open", guarded)
    try:
        if whole_repo:
            changed = ft._mutation(root, "a" * 40, ["nested/file"], before)
            assert changed
        else:
            after = ft._manifest(root, ["nested/file"])
            assert after != before
    except (ft.FenceError, OSError):
        pass
    assert attempted == [], "inspection tried to open a file through a candidate parent symlink"


def test_a_candidate_head_fifo_cannot_block_coordinator_inspection(tmp_path, monkeypatch):
    from lanectl import fenced_train as ft
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    os.mkfifo(root / ".git/HEAD")
    real_open = os.open
    blocking_attempts = []
    def guarded(path, flags, *args, **kwargs):
        candidate = Path(path)
        if not candidate.is_absolute() and kwargs.get("dir_fd") is not None:
            candidate = Path(os.readlink(f"/proc/self/fd/{kwargs['dir_fd']}")) / candidate
        if candidate.name == "HEAD" and stat.S_ISFIFO(os.lstat(candidate).st_mode):
            if not flags & os.O_NONBLOCK:
                blocking_attempts.append(str(candidate))
                raise PermissionError("synthetic guard prevented a blocking FIFO open")
        return real_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(ft.os, "open", guarded)
    try:
        assert ft._mutation(root, "a" * 40, [], {})
    except (ft.FenceError, OSError):
        pass
    assert blocking_attempts == []


def test_legitimate_leaf_link_metadata_remains_inspectable(tmp_path):
    from lanectl import fenced_train as ft
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / ".git/HEAD").write_text("a" * 40 + "\n")
    (root / "leaf").symlink_to("missing-external-target")
    before = ft._manifest(root, ["leaf"])
    assert before == {"leaf": ("link", "missing-external-target")}
    assert ft._mutation(root, "a" * 40, ["leaf"], before) == ""
