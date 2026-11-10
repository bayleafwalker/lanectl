"""Acceptance: find the lanectl checkout without LANECTL_HOME (planner-owned)."""
from pathlib import Path

from lanectl import config


def _checkout(tmp_path):
    home = tmp_path / "checkout"
    (home / "governance").mkdir(parents=True)
    (home / "governance" / "repos.toml").write_text("")
    (home / "backlog" / "some-item").mkdir(parents=True)
    return home


def test_env_wins(tmp_path, monkeypatch):
    home = _checkout(tmp_path)
    monkeypatch.setenv("LANECTL_HOME", str(tmp_path / "elsewhere"))
    monkeypatch.chdir(home)
    assert config.home() == tmp_path / "elsewhere"


def test_walks_up_from_working_directory(tmp_path, monkeypatch):
    home = _checkout(tmp_path)
    monkeypatch.delenv("LANECTL_HOME", raising=False)
    monkeypatch.chdir(home / "backlog" / "some-item")
    assert config.home().resolve() == home.resolve()


def test_checkout_root_itself(tmp_path, monkeypatch):
    home = _checkout(tmp_path)
    monkeypatch.delenv("LANECTL_HOME", raising=False)
    monkeypatch.chdir(home)
    assert config.home().resolve() == home.resolve()


def test_falls_back_to_package_checkout(tmp_path, monkeypatch):
    monkeypatch.delenv("LANECTL_HOME", raising=False)
    bare = tmp_path / "bare"
    bare.mkdir()
    monkeypatch.chdir(bare)
    assert config.home() == Path(config.__file__).resolve().parents[2]


def test_directory_without_repos_toml_is_not_a_checkout(tmp_path, monkeypatch):
    monkeypatch.delenv("LANECTL_HOME", raising=False)
    fake = tmp_path / "fake"
    (fake / "governance").mkdir(parents=True)
    monkeypatch.chdir(fake)
    assert config.home() == Path(config.__file__).resolve().parents[2]
