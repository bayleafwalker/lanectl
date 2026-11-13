"""Descriptor-relative inspection: parent links are never followed."""
import os

from lanectl import fenced_train as ft


def _repo(tmp_path):
    root = tmp_path / "repo"
    (root / "d").mkdir(parents=True)
    (root / "d/f").write_text("x")
    (root / "link").symlink_to("d/f")
    (root / ".git").mkdir()
    (root / ".git/HEAD").write_text("a" * 40 + "\n")
    return root


def test_parent_symlink_is_unreadable_not_followed(tmp_path):
    root = _repo(tmp_path)
    tracked = ["d/f", "link"]
    before = ft._manifest(root, tracked)
    assert before["link"] == ("link", "d/f")
    outside = tmp_path / "out"
    outside.mkdir()
    (outside / "f").write_text("x")
    (root / "d/f").unlink()
    (root / "d").rmdir()
    (root / "d").symlink_to(outside, target_is_directory=True)
    after = ft._manifest(root, tracked)
    assert after["d/f"][0] == "unreadable"
    assert after["link"] == before["link"]


def test_head_fifo_and_symlinked_repo_are_rejected(tmp_path):
    root = _repo(tmp_path)
    commit = "a" * 40
    assert ft._mutation(root, commit, [], {}) == ""
    (root / ".git/HEAD").unlink()
    os.mkfifo(root / ".git/HEAD")
    assert ft._mutation(root, commit, [], {}) == "HEAD changed"
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    assert not ft._read_head(alias, commit)
