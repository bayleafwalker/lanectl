"""Tests: find the checkout by walking up from the working directory (bx-home-default)."""
from pathlib import Path

from lanectl import config


def _make_checkout(root: Path) -> Path:
    (root / "governance").mkdir(parents=True, exist_ok=True)
    (root / "governance" / "repos.toml").write_text("")
    return root


def test_nearest_checkout_wins(tmp_path, monkeypatch):
    outer = _make_checkout(tmp_path / "outer")
    inner = _make_checkout(outer / "nested")
    work = inner / "backlog" / "item"
    work.mkdir(parents=True)
    monkeypatch.delenv("LANECTL_HOME", raising=False)
    monkeypatch.chdir(work)
    assert config.home().resolve() == inner.resolve()


def test_walk_up_finds_deep_ancestor(tmp_path, monkeypatch):
    home = _make_checkout(tmp_path / "checkout")
    work = home / "a" / "b" / "c"
    work.mkdir(parents=True)
    monkeypatch.delenv("LANECTL_HOME", raising=False)
    monkeypatch.chdir(work)
    assert config.home().resolve() == home.resolve()


def test_empty_env_falls_through_to_walk_up(tmp_path, monkeypatch):
    home = _make_checkout(tmp_path / "checkout")
    work = home / "backlog"
    work.mkdir()
    monkeypatch.setenv("LANECTL_HOME", "")
    monkeypatch.chdir(work)
    assert config.home().resolve() == home.resolve()


def test_directory_without_repos_toml_is_skipped(tmp_path, monkeypatch):
    home = _make_checkout(tmp_path / "checkout")
    fake = home / "fake"
    (fake / "governance").mkdir(parents=True)
    monkeypatch.delenv("LANECTL_HOME", raising=False)
    monkeypatch.chdir(fake)
    assert config.home().resolve() == home.resolve()
