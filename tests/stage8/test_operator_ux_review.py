"""Review findings on the operator-UX redesign: help, status, doctor, reap, effects, vocabulary."""
import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from lanectl import cli, doctor, html_style, reap, render, runner, status, tui, vocab

ACC = "def test_ok():\n    assert True\n"


def _walk(parser, path=()):
    """Yield (command path, parser) for every parser, depth first."""
    yield path, parser
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction):
            for name, sp in a.choices.items():
                yield from _walk(sp, (*path, name))


def _commands():
    parser, _, _ = cli._build_parser()
    return [p for p, _ in _walk(parser) if p]


@pytest.mark.parametrize("path", _commands(), ids=" ".join)
def test_every_subcommand_help_is_its_own(path, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main([*path, "--help"])
    out = capsys.readouterr().out
    assert e.value.code == 0
    assert out.startswith(f"usage: lanectl {' '.join(path)}"), out[:80]
    parser = dict(_walk(cli._build_parser()[0]))[path]
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction):
            continue
        shown = a.option_strings[-1] if a.option_strings else (
            a.metavar or (next(iter(a.choices)) if a.choices else a.dest))
        assert shown in out


def test_land_help_documents_train_id_and_dry_run(capsys):
    with pytest.raises(SystemExit):
        cli.main(["land", "--help"])
    out = capsys.readouterr().out
    assert "train_id" in out and "--dry-run" in out and "Start here" not in out


def test_every_option_has_help_and_the_table_has_no_stale_keys(monkeypatch):
    monkeypatch.setattr(cli, "_fill_help", lambda *a, **k: None)
    bare, _, _ = cli._build_parser()
    missing = {}
    for path, p in _walk(bare):
        for a in p._actions:
            if isinstance(a, argparse._SubParsersAction) or a.dest == "help":
                continue
            if a.help is None:
                missing[f"{' '.join(path)}:{a.dest}"] = a
    assert not set(missing) - set(cli._MISSING_HELP), set(missing) - set(cli._MISSING_HELP)
    assert not set(cli._MISSING_HELP) - set(missing), set(cli._MISSING_HELP) - set(missing)
    monkeypatch.undo()
    filled, _, _ = cli._build_parser()
    assert [(p, a.dest) for p, sp in _walk(filled) for a in sp._actions if not a.help
            and not isinstance(a, argparse._SubParsersAction)] == []


def test_invalid_choice_is_not_an_unknown_command(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["review-progress", "a1", "maybe", "--progress", "p", "--remaining", "r", "--reason", "x"])
    err = capsys.readouterr().err
    assert e.value.code == 2 and "invalid choice: 'maybe'" in err and "unknown command" not in err


def test_version_matches_pyproject_in_a_checkout():
    import tomllib
    pyproject = Path(cli.__file__).resolve().parents[2] / "pyproject.toml"
    assert cli._version() == tomllib.loads(pyproject.read_text())["project"]["version"]


def test_run_breaker_exits_75_not_the_not_found_code(estate, monkeypatch, capsys):
    claim = SimpleNamespace(attempt_id="a1", model="m")
    monkeypatch.setattr(runner, "admit", lambda *a, **k: claim)
    monkeypatch.setattr(runner, "execute", lambda *a, **k: "a1 -> rejected: infra: down")
    assert cli.main(["run"]) == 75
    assert "breaker" in capsys.readouterr().out


def test_invalid_backend_marker_is_a_message_not_a_traceback(estate, monkeypatch, capsys):
    monkeypatch.setattr(cli, "open_log", lambda: (_ for _ in ()).throw(ValueError("invalid lanectl backend marker")))
    assert cli.main(["events"]) == 1
    err = capsys.readouterr().err
    assert "error:" in err and "fix:" in err and "Traceback" not in err


# --- F2 / status

def _doc(**kw):
    base = {"needs_you": [], "blocked": [], "warnings": []}
    return {**base, **kw}


def test_next_uses_the_first_row_of_each_state():
    rows = [{"state": "parked", "id": "first", "repo": "r"}, {"state": "parked", "id": "second", "repo": "r"}]
    assert status._next(_doc(needs_you=rows)) == ["lanectl backlog show first"]


def test_status_never_suggests_publishing_a_held_draft(estate, capsys):
    _, release, _ = estate
    release("hold-me", ACC)
    toml = Path(__import__("os").environ["LANECTL_HOME"]) / "backlog" / "hold-me" / "release.toml"
    toml.write_text("draft = true\n" + toml.read_text())
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "next: lanectl backlog show hold-me" in out and "publish" not in out
    assert cli.main(["status", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)   # reasons may quote ready's text; commands may not
    assert not any("publish" in c for c in [*doc["next"], *(b["fix"] for b in doc["blocked"])])


def test_status_stays_within_24_lines_and_caps_warnings():
    many = lambda n, **kw: [{"id": f"i{i}", "state": "parked", "reason": "r", "tries": 1, "repo": "x",
                              "reasons": ["release is a draft"], "fix": "f", **kw} for i in range(n)]
    doc = {"context": {"home": "h", "source": "env", "repos": ["x"], "events": 1},
           "landed": {"count": 2, "ids": ["a", "b"]}, "counts": {"ready": 4},
           "needs_you": many(9), "blocked": many(9),
           "warnings": [{"level": "warn", "check": f"c{i}", "detail": "d", "fix": f"fix{i}"} for i in range(9)],
           "in_flight": [{"id": f"r{i}", "state": "claimed", "age": "1m ago"} for i in range(9)],
           "lanes": [], "next": ["lanectl status"]}
    text = status.format_text(doc)
    assert len(text.splitlines()) <= 24 and "more (lanectl doctor)" in text
    assert len(status.format_text(doc, show_all=True).splitlines()) > 24


# --- F3 doctor

def test_doctor_collapse_keeps_distinct_findings_and_counts_raw():
    f = [doctor.Finding(doctor.WARN, "policy", "first problem", fix="fix1"),
         doctor.Finding(doctor.WARN, "policy", "second problem", fix="fix2")]
    out = doctor.collapse(f)
    assert [x.detail for x in out] == ["first problem", "second problem"]


def test_doctor_summary_counts_every_finding(monkeypatch, capsys):
    drift = [doctor.Finding(doctor.WARN, "base-drift", f"r{i}", subject=f"r{i}") for i in range(3)]
    monkeypatch.setattr(doctor, "run", lambda log, **k: drift)
    assert doctor._cmd(SimpleNamespace(json=False), None) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2 and "3 x" in lines[0] and lines[1].endswith("0 ok, 3 warn, 0 error")


# --- F5 reap

def _claim(aid, ts):
    return {"type": "item.claimed", "item_id": "i1", "ts": ts, "data": {"attempt_id": aid}}


def test_reap_selection_includes_finished_but_undecided_attempts():
    old = "2026-01-01T00:00:00+00:00"
    events = [_claim("a1", old),
              {"type": "attempt.finished", "item_id": "i1", "ts": old, "data": {"attempt_id": "a1"}}]
    now = datetime.now(timezone.utc)
    undecided, abandoned = reap.select(events, now, 3600)
    assert [e["data"]["attempt_id"] for e, _ in undecided] == ["a1"] and abandoned == []
    events.append({"type": "decision.recorded", "item_id": "i1", "ts": old,
                   "data": {"attempt_id": "a1", "decision": "rejected", "reasons": []}})
    assert reap.select(events, now, 3600) == ([], [])


def test_reap_dry_run_lists_what_reap_would_recover(estate, monkeypatch, capsys):
    _, release, log = estate
    release("aa", ACC)
    old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    sel = ([({"data": {"attempt_id": "fin-1"}}, "aa")], [({"data": {"attempt_id": "open-1"}}, {})])
    monkeypatch.setattr(reap, "select", lambda *a, **k: sel)
    assert cli.main(["reap", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "fin-1" in out and "open-1" in out and "2 open or undecided" in out


# --- F8 effects

def test_land_unknown_train_is_not_found_even_on_dry_run(estate, capsys):
    for extra in ([], ["--dry-run"], ["--yes"]):
        assert cli.main(["land", "no-such-train", *extra]) == 3
        assert "would" not in capsys.readouterr().out


def test_effect_exit_code_comes_from_the_outcome_not_the_text(capsys):
    args = SimpleNamespace(dry_run=False, yes=True)
    assert cli._effect(args, "x", "x", lambda: (5, "already tried and refused")) == 5
    assert cli._effect(args, "x", "x", lambda: (0, "done")) == 0
    assert cli._landed("landed ['a'] (already recorded); use work reconcile")[0] == 0
    assert cli._landed("t1: failed train; rebuild")[0] == 5


# --- T1 / vocabulary

@pytest.mark.parametrize("word", ["pending", "in_progress", "open", "in-progress"])
def test_owner_statuses_are_classified(word):
    assert vocab.classify(word) != "unknown"
    assert vocab.classify("pending") == vocab.classify("open") == "idle"


def test_owner_blocked_true_is_needs_you():
    value = {"item": {"status": "open", "blocked": True}}
    row = {"facts": {"work.public.item-v1": {"value": value}}}
    assert tui._state(row) == "blocked" and vocab.classify(tui._state(row)) == "needs"
    value["item"]["blocked"] = False
    assert tui._state(row) == "open"


def test_every_state_has_a_known_kind_and_a_reason():
    for word, (kind, why) in vocab.STATES.items():
        assert kind in vocab.SYMBOLS and why, word


def test_status_tui_and_html_classify_every_state_identically():
    assert (render.NEEDS, render.FAILED, render.RUNNING, render.OK, render.IDLE, render.UNKNOWN) == tuple(
        vocab.SYMBOLS[k] for k in ("needs", "failed", "running", "ok", "idle", "unknown"))
    rows = [{"state": s, "id": f"id-{s}", "reason": "", "tries": 1, "repo": "x"} for s in status._NEEDS]
    doc = {"context": {"home": "h", "source": "env", "repos": ["x"], "events": 1},
           "landed": {"count": 0, "ids": []}, "counts": {}, "needs_you": rows, "blocked": [],
           "warnings": [], "in_flight": [], "lanes": [], "next": []}
    text = status.format_text(doc)
    for word in [*vocab.STATES, "mystery"]:
        symbol = vocab.SYMBOLS[vocab.classify(word)]
        assert vocab.mark(word) == f"{symbol} {word}"
        assert render.state(word) == f"{symbol} {word}"          # CLI (no colour off a TTY)
        assert symbol in html_style.badge(word)                  # HTML
    for s in status._NEEDS:                                      # status rows
        assert f"{vocab.SYMBOLS[vocab.classify(s)]} {s}" in text
    assert {vocab.classify(s) for s in status._NEEDS} == {"needs"}
    assert vocab.classify("claimed") == vocab.classify("gated") == "running"


# --- T2 / T3 / T4 / --no-color

def test_missing_default_colour_support_falls_back_to_no_colour(monkeypatch):
    def refuse():
        raise tui.curses.error("no default colours")
    monkeypatch.setattr(tui.curses, "use_default_colors", refuse)
    attrs = tui._attributes(True)
    assert attrs["needs"] == tui.curses.A_BOLD and attrs["ok"] == 0


@pytest.mark.parametrize("value", ["0", "0.5", "-3"])
def test_tui_refresh_below_one_second_is_a_usage_error(value, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["tui", "--refresh", value])
    assert e.value.code == 2 and "at least 1 second" in capsys.readouterr().err


def test_tui_off_a_terminal_prints_status(estate, monkeypatch, capsys):
    monkeypatch.setattr(tui, "_interactive", lambda: False)
    assert cli.main(["tui"]) == 0
    tui_out = capsys.readouterr().out
    assert cli.main(["status"]) == 0
    assert tui_out == capsys.readouterr().out


def test_status_segments_tolerate_a_missing_observation_time():
    segs = tui._status_segments({"observed_at": None, "sources": {}}, None, [], None)
    assert segs[0][0] == "updated ?"


def test_root_no_color_survives_the_tui_subparser():
    parser, _, _ = cli._build_parser()
    assert parser.parse_args(["--no-color", "tui"]).no_color is True
    assert parser.parse_args(["tui", "--no-color"]).tui_no_color is True
