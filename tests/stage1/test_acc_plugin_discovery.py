"""Acceptance: plugins are discovered, not wired by anchor lines (planner-owned)."""
import inspect
import json

from lanectl import cli
from lanectl.events import EventLog


def _names(mods):
    return [m.__name__.rsplit(".", 1)[-1] for m in mods]


def test_lanectl_plugins_are_discovered_sorted():
    names = _names(cli.discover_plugins("lanectl"))
    assert {"capacity", "lint_release", "reap", "report", "usage_hook"} <= set(names)
    assert "runner" not in names and "cli" not in names     # no register() there
    assert names == sorted(names)


def test_cli_has_no_anchor_wiring():
    src = inspect.getsource(cli)
    assert "@anchor" not in src and "PLUGINS.append" not in src


def test_new_module_needs_no_cli_edit(tmp_path, monkeypatch):
    pkg = tmp_path / "plugpkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "zeta.py").write_text("def register(sub):\n    return {}\n")
    (pkg / "alpha.py").write_text("def register(sub):\n    return {}\n")
    (pkg / "helper.py").write_text("VALUE = 1\n")
    (pkg / "fake.py").write_text("register = 3\n")             # not callable
    monkeypatch.syspath_prepend(str(tmp_path))
    assert _names(cli.discover_plugins("plugpkg")) == ["alpha", "zeta"]


def test_existing_commands_still_parse(capsys):
    for cmd in (["report", "--help"], ["capacity", "--help"], ["lint-release", "--help"], ["reap", "--help"]):
        try:
            cli.main(cmd)
        except SystemExit as e:
            assert e.code == 0, cmd


def test_events_type_filter(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LANECTL_STATE", str(tmp_path))
    log = EventLog()
    log.append("usage.recorded", {"provider": "opencode", "source": "adapter", "units": {"output_tokens": 5}})
    log.append("item.parked", {"reason": "rr"}, item_id="it-1")
    log.append("item.requeued", {"reason": "rr"}, item_id="it-1")
    assert cli.main(["events", "--type", "item.parked", "--type", "item.requeued"]) == 0
    types = [json.loads(line)["type"] for line in capsys.readouterr().out.splitlines()]
    assert types == ["item.parked", "item.requeued"]
    assert cli.main(["events", "--type", "item.parked", "--item", "nope"]) == 0
    assert capsys.readouterr().out == ""
